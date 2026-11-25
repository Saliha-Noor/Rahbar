"""Turns a question into an AskResponse. The query pipeline of section 3.2.

Order: cache check, retrieve, relevance floor (abstain before any model call), generate,
validate (one retry inside the provider, then a canned fallback), citation check, cache
only what is safe. AskRequest has no history field, so every request is standalone and no
follow-up question can ever reach the cache.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from ..config import Settings
from ..logjson import request_id_var
from ..metrics_rag import (
    ABSTENTIONS,
    CACHE_HITS,
    CACHE_MISSES,
    FALLBACKS,
    GENERATION_SECONDS,
    INJECTION_FLAGS,
    RETRIEVAL_SECONDS,
    STAGE_SECONDS,
    TOP1_SCORE,
)
from ..providers.llm.base import LLMProvider
from ..providers.llm.errors import GenerationFailed
from ..retrieval.base import Retriever
from ..schemas import Answer, AskResponse, Passage, RetrievedRef
from .cache import SemanticCache
from .embedder import embed_query
from .guard import keep_valid_citations, question_flags, redact_passages
from .prompt import build_messages
from .trace import Timer, emit, prompt_hash

log = logging.getLogger("rahbar.answer")

ABSTAIN_TEXT = "The documents I have access to do not cover this question."
FALLBACK_TEXT = "I could not produce a reliable answer right now. Please try again or rephrase."


def _plain(text: str) -> Answer:
    return Answer(reasoning="", answer=text, citations=[], answered_from_context=False,
                  confidence="low")


def _build(rid: str, ans: Answer, passages: list[Passage], provider: LLMProvider) -> AskResponse:
    return AskResponse(
        request_id=rid,
        answer=ans.answer,
        citations=ans.citations,
        answered_from_context=ans.answered_from_context,
        confidence=ans.confidence,
        retrieved=[
            RetrievedRef(chunk_id=p.chunk_id, source=p.source, section=p.section,
                         page=p.page, score=p.score)
            for p in passages
        ],
        provider=provider.name,
    )


def _log(settings: Settings, passages: list[Passage], resp: AskResponse, dropped: int) -> None:
    log.info(
        "answered",
        extra={
            "top_k": settings.top_k,
            "chunk_ids": [p.chunk_id for p in passages],
            "scores": [round(p.score, 4) for p in passages],
            "answered_from_context": resp.answered_from_context,
            "abstained": not resp.answered_from_context,
            "dropped_citations": dropped,
        },
    )


def _trace(settings: Settings, retriever: Any, provider: LLMProvider, rid: str, question: str,
           resp: AskResponse, outcome: str, cache_state: str, tm: Timer, guard: list[dict[str, Any]],
           messages: list[dict[str, str]] | None, passages: list[Passage]) -> None:
    """D1: one trace record per query. Must never raise."""
    try:
        info: dict[str, Any] = getattr(retriever, "last_info", lambda: {})() if outcome != "cache_hit" else {}
        idx: dict[str, Any] = getattr(retriever, "index_info", lambda: {})()
        by_id = {p.chunk_id: p for p in passages}
        retrieved = [{"chunk_id": r.chunk_id, "doc_id": getattr(by_id.get(r.chunk_id), "doc_id", ""),
                      "doc_version": getattr(by_id.get(r.chunk_id), "doc_version", ""),
                      "source": r.source, "section": r.section, "page": r.page,
                      "score": round(r.score, 4)} for r in resp.retrieved]
        rec = {
            "event": "trace", "trace_id": rid, "ts": datetime.now(timezone.utc).isoformat(),
            "query": question, "rewritten_query": None,
            "embedding": {"model": settings.embed_model, "version": idx.get("embed_version", "unknown")},
            "collection": {"name": idx.get("collection", settings.collection),
                           "index_id": idx.get("index_id"), "chunk_size": idx.get("chunk_size")},
            "retrieved": retrieved,
            "filters": {"where": info.get("filter"), "off_reason": info.get("filter_off_reason"),
                        "exact_terms": info.get("exact_terms", [])},
            "reranked_order": info.get("final_order", [r["chunk_id"] for r in retrieved]),
            "vector_order": info.get("vector_order"),
            "prompt_hash": prompt_hash(messages) if messages else None, "prompt": messages,
            "model": {"provider": provider.name, "name": settings.llm_model,
                      "params": {"temperature": settings.temperature, "seed": settings.llm_seed,
                                 "top_k": settings.top_k, "relevance_floor": settings.relevance_floor}},
            "response": resp.answer, "citations": [c.model_dump() for c in resp.citations],
            "answered_from_context": resp.answered_from_context, "outcome": outcome,
            "guardrails": guard, "latency_ms": {**tm.ms, "total": tm.total()}, "cache": cache_state,
        }
        for stage, ms in tm.ms.items():
            STAGE_SECONDS.labels(stage).observe(ms / 1000)
        if resp.retrieved:
            TOP1_SCORE.observe(max(r.score for r in resp.retrieved))
        emit(rec, settings.trace_dir)
    except Exception:   # tracing is best-effort
        log.warning("trace failed", exc_info=True)


def answer_question(
    question: str,
    retriever: Retriever,
    provider: LLMProvider,
    settings: Settings,
    cache: SemanticCache | None = None,
    use_cache: bool = True,
) -> AskResponse:
    rid = request_id_var.get()
    tm = Timer()
    index_id = getattr(retriever, "index_id", lambda: "stub")()
    guard = question_flags(question)
    for _ in guard:
        INJECTION_FLAGS.labels("question").inc()
    cache_state = "off" if cache is None else ("miss" if use_cache else "bypass")

    # 2. cache check
    vec: list[float] = []
    if cache is not None:
        try:
            vec = tm.run("embed", embed_query, question, settings)
            if use_cache:
                hit, _sim = tm.run("cache", cache.lookup, vec, index_id)
                if hit:
                    CACHE_HITS.inc()
                    log.info("cache hit", extra={"cache": "hit"})
                    resp = AskResponse(**{**hit, "request_id": rid})
                    _trace(settings, retriever, provider, rid, question, resp, "cache_hit", "hit",
                           tm, guard, None, [])
                    return resp
                CACHE_MISSES.inc()
        except Exception:  # embedding or Redis trouble: skip the cache, never fail the request
            vec = []

    # 3-4. retrieve
    started = time.perf_counter()
    passages = tm.run("retrieve", retriever.retrieve, question, k=settings.top_k)
    RETRIEVAL_SECONDS.observe(time.perf_counter() - started)

    # relevance floor: honest abstention, before any model call
    if not passages or passages[0].score < settings.relevance_floor:
        ABSTENTIONS.inc()
        resp = _build(rid, _plain(ABSTAIN_TEXT), passages, provider)
        _log(settings, passages, resp, dropped=0)
        _trace(settings, retriever, provider, rid, question, resp, "abstained_floor", cache_state,
               tm, guard, None, passages)
        return resp

    # retrieval rail (D4): cut instruction-like sentences out of the evidence before prompting
    sent, actions = redact_passages(passages)
    for _ in actions:
        INJECTION_FLAGS.labels("retrieved").inc()
    guard = guard + actions
    messages = build_messages(question, sent)

    # 5-7. generate and validate (the retry is inside the provider), else fall back
    started = time.perf_counter()
    try:
        answer = tm.run("generate", provider.generate, question, sent)
    except GenerationFailed:
        FALLBACKS.inc()
        resp = _build(rid, _plain(FALLBACK_TEXT), passages, provider)
        _log(settings, passages, resp, dropped=0)
        _trace(settings, retriever, provider, rid, question, resp, "fallback", cache_state,
               tm, guard, messages, passages)
        return resp
    finally:
        GENERATION_SECONDS.observe(time.perf_counter() - started)

    answer, dropped = keep_valid_citations(answer, passages)
    outcome = "answered"
    if answer.answered_from_context and not answer.citations:
        ABSTENTIONS.inc()  # claimed an answer but cited nothing real: do not trust it
        answer = _plain(ABSTAIN_TEXT)
        outcome = "abstained_no_valid_citation"
    elif not answer.answered_from_context:
        outcome = "abstained_by_model"

    resp = _build(rid, answer, passages, provider)
    # 8. cache only what is safe: a grounded answer with valid citations
    if cache is not None and use_cache and vec and answer.answered_from_context:
        cache.store(vec, resp.model_dump(), index_id)
    _log(settings, passages, resp, dropped)
    _trace(settings, retriever, provider, rid, question, resp, outcome, cache_state, tm, guard,
           messages, passages)
    return resp

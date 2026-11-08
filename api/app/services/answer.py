"""Turns a question into an AskResponse. The query pipeline of section 3.2.

Order: cache check, retrieve, relevance floor (abstain before any model call), generate,
validate (one retry inside the provider, then a canned fallback), citation check, cache
only what is safe. AskRequest has no history field, so every request is standalone and no
follow-up question can ever reach the cache.
"""

from __future__ import annotations

import logging
import time

from ..config import Settings
from ..logjson import request_id_var
from ..metrics_rag import (
    ABSTENTIONS,
    CACHE_HITS,
    CACHE_MISSES,
    FALLBACKS,
    GENERATION_SECONDS,
    RETRIEVAL_SECONDS,
)
from ..providers.llm.base import LLMProvider
from ..providers.llm.errors import GenerationFailed
from ..retrieval.base import Retriever
from ..schemas import Answer, AskResponse, Passage, RetrievedRef
from .cache import SemanticCache
from .embedder import embed_query
from .guard import keep_valid_citations

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


def answer_question(
    question: str,
    retriever: Retriever,
    provider: LLMProvider,
    settings: Settings,
    cache: SemanticCache | None = None,
) -> AskResponse:
    rid = request_id_var.get()
    index_id = getattr(retriever, "index_id", lambda: "stub")()

    # 2. cache check
    vec: list[float] = []
    if cache is not None:
        try:
            vec = embed_query(question, settings)
            hit, _sim = cache.lookup(vec, index_id)
            if hit:
                CACHE_HITS.inc()
                log.info("cache hit", extra={"cache": "hit"})
                return AskResponse(**{**hit, "request_id": rid})
            CACHE_MISSES.inc()
        except Exception:  # embedding or Redis trouble: skip the cache, never fail the request
            vec = []

    # 3-4. retrieve
    started = time.perf_counter()
    passages = retriever.retrieve(question, k=settings.top_k)
    RETRIEVAL_SECONDS.observe(time.perf_counter() - started)

    # relevance floor: honest abstention, before any model call
    if not passages or passages[0].score < settings.relevance_floor:
        ABSTENTIONS.inc()
        resp = _build(rid, _plain(ABSTAIN_TEXT), passages, provider)
        _log(settings, passages, resp, dropped=0)
        return resp

    # 5-7. generate and validate (the retry is inside the provider), else fall back
    started = time.perf_counter()
    try:
        answer = provider.generate(question, passages)
    except GenerationFailed:
        FALLBACKS.inc()
        resp = _build(rid, _plain(FALLBACK_TEXT), passages, provider)
        _log(settings, passages, resp, dropped=0)
        return resp
    finally:
        GENERATION_SECONDS.observe(time.perf_counter() - started)

    answer, dropped = keep_valid_citations(answer, passages)
    if answer.answered_from_context and not answer.citations:
        ABSTENTIONS.inc()  # claimed an answer but cited nothing real: do not trust it
        answer = _plain(ABSTAIN_TEXT)

    resp = _build(rid, answer, passages, provider)
    # 8. cache only what is safe: a grounded answer with valid citations
    if cache is not None and vec and answer.answered_from_context:
        cache.store(vec, resp.model_dump(), index_id)
    _log(settings, passages, resp, dropped)
    return resp

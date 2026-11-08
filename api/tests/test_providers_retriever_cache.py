"""Tests for the Ollama provider, the Chroma retriever and the semantic cache, with fakes."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.providers.llm.errors import GenerationFailed
from app.providers.llm.ollama import OllamaProvider
from app.retrieval import chroma as chroma_mod
from app.retrieval.chroma import ChromaRetriever
from app.schemas import Passage
from app.services import cache as cache_mod

GOOD = json.dumps({"reasoning": "r", "answer": "80%", "answered_from_context": True,
                   "confidence": "high",
                   "citations": [{"source": "a.pdf", "section": "1.21", "page": 2}]})


class FakeResp:
    def __init__(self, content: str) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return {"message": {"content": self.content}, "prompt_eval_count": 5, "eval_count": 7}


def _passages() -> list[Passage]:
    return [Passage(chunk_id="c", text="t", source="a.pdf", section="1.21", page=2, score=0.9)]


def test_ollama_retries_once_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    replies = iter(["not json at all", GOOD])
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResp(next(replies)))
    out = OllamaProvider(Settings()).generate("q?", _passages())
    assert out.answered_from_context is True


def test_ollama_gives_up_after_one_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def post(*a: Any, **k: Any) -> FakeResp:
        calls.append(1)
        return FakeResp("prose, not JSON")

    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(GenerationFailed):
        OllamaProvider(Settings()).generate("q?", _passages())
    assert len(calls) == 2


def test_ollama_sends_schema_and_temperature(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def post(url: str, json: dict[str, Any], **k: Any) -> FakeResp:
        seen.update(json)
        return FakeResp(GOOD)

    monkeypatch.setattr(httpx, "post", post)
    OllamaProvider(Settings(temperature=0.2)).generate("q?", _passages())
    assert seen["options"]["temperature"] == 0.2
    assert "properties" in seen["format"]


class FakeCollection:
    def __init__(self) -> None:
        self.query_where: Any = "unset"

    def query(self, query_embeddings: Any, n_results: int, where: Any, include: Any) -> dict[str, Any]:
        self.query_where = where
        return {"ids": [["c1"]], "documents": [["text"]], "distances": [[0.25]],
                "metadatas": [[{"source": "a.pdf", "section": "5.4 Warning", "page": 3}]]}

    def get(self, where_document: Any, where: Any, limit: int, include: Any) -> dict[str, Any]:
        return {"ids": ["c2"], "documents": ["clause 1.21 text"],
                "metadatas": [{"source": "a.pdf", "section": "1.21 Attendance", "page": 4}]}


def _retriever(monkeypatch: pytest.MonkeyPatch, col: FakeCollection) -> ChromaRetriever:
    monkeypatch.setattr(chroma_mod, "embed_query", lambda q, s: [0.1])
    r = ChromaRetriever.__new__(ChromaRetriever)
    r.settings = Settings(relevance_floor=0.5)
    r._collection = lambda: col  # type: ignore[method-assign]
    return r


def test_retriever_filters_superseded_and_converts_distance(monkeypatch: pytest.MonkeyPatch) -> None:
    col = FakeCollection()
    out = _retriever(monkeypatch, col).retrieve("What is the warning CGPA?", 5)
    assert col.query_where == {"superseded": False}
    assert out[0].score == pytest.approx(0.75)


def test_retriever_drops_the_filter_when_an_older_version_is_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    col = FakeCollection()
    _retriever(monkeypatch, col).retrieve("What did the 2023 rules say about attendance?", 5)
    assert col.query_where is None


def test_retriever_adds_exact_term_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _retriever(monkeypatch, FakeCollection()).retrieve("What does clause 1.21 require?", 5)
    assert {p.chunk_id for p in out} == {"c1", "c2"}


class FakeRedis:
    store: dict[str, str] = {}

    def __init__(self, **kw: Any) -> None:
        pass

    def scan_iter(self, pattern: str, count: int = 0) -> Any:
        prefix = pattern.rstrip("*")
        return [k for k in self.store if k.startswith(prefix)]

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.store[key] = value

    def ping(self) -> bool:
        return True


def test_cache_hit_needs_the_threshold_and_the_same_index_id(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeRedis.store = {}
    monkeypatch.setattr(cache_mod.redis, "Redis", FakeRedis)
    cache = cache_mod.SemanticCache(Settings(cache_threshold=0.9))
    cache.store([1.0, 0.0], {"answer": "x"}, "idx1")
    hit, sim = cache.lookup([1.0, 0.0], "idx1")
    assert hit == {"answer": "x"} and sim == pytest.approx(1.0)
    assert cache.lookup([0.0, 1.0], "idx1")[0] is None          # not similar enough
    assert cache.lookup([1.0, 0.0], "idx2")[0] is None          # re-indexed: old entries orphaned

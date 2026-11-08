"""The real retriever (sections 3.2 and 4.4)."""

from __future__ import annotations

import os
import re
import time
from typing import Any

from ..config import Settings
from ..schemas import Passage
from ..services.embedder import embed_query

# A question that names an older version turns the superseded filter off.
OLD_VERSION = re.compile(
    r"\b(2023|older|old version|previous|former|superseded|earlier version)\b", re.I
)
# Exact terms that embeddings blur: course codes (CS-101), clause numbers (1.21), CGPA (2.00).
EXACT = re.compile(r"\b(?:[A-Za-z]{2,4}-?\d{3,4}|\d+(?:\.\d+)+)\b")


class ChromaRetriever:
    name = "chroma"

    def __init__(self, settings: Settings) -> None:
        import chromadb  # the thin client, from chromadb-client in requirements.txt
        from chromadb.config import Settings as ChromaSettings

        self.settings = settings
        self.client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port,
                                          settings=ChromaSettings(anonymized_telemetry=False))
        self._idx = "none"
        self._idx_at = 0.0

    def _collection(self) -> Any:
        return self.client.get_collection(self.settings.collection)

    def index_id(self) -> str:
        """Which index build is this? Part of every cache key. Refreshed every 30 s."""
        if time.time() - self._idx_at > 30:
            self._idx = str((self._collection().metadata or {}).get("index_id", "none"))
            self._idx_at = time.time()
        return self._idx

    def retrieve(self, question: str, k: int) -> list[Passage]:
        col = self._collection()
        # SUPERSEDED_FILTER=off exists only to demonstrate failure mode E (docs/FAILURE-ANALYSIS.md).
        no_filter = OLD_VERSION.search(question) or os.environ.get("SUPERSEDED_FILTER") == "off"
        where = None if no_filter else {"superseded": False}
        res = col.query(query_embeddings=[embed_query(question, self.settings)], n_results=k,
                        where=where, include=["documents", "metadatas", "distances"])
        found: dict[str, Passage] = {}
        for cid, doc, m, dist in zip(res["ids"][0], res["documents"][0],
                                     res["metadatas"][0], res["distances"][0]):
            found[cid] = Passage(chunk_id=cid, text=doc, source=m["source"], section=m["section"],
                                 page=m.get("page"), score=1 - dist)
        # Hybrid step: embeddings blur exact terms, so also look for them literally.
        for term in set(EXACT.findall(question)):
            hit = col.get(where_document={"$contains": term}, where=where, limit=3,
                          include=["documents", "metadatas"])
            for cid, doc, m in zip(hit["ids"], hit["documents"], hit["metadatas"]):
                found.setdefault(cid, Passage(
                    chunk_id=cid, text=doc, source=m["source"], section=m["section"],
                    page=m.get("page"), score=self.settings.relevance_floor + 0.01))
        return sorted(found.values(), key=lambda p: p.score, reverse=True)[:k]

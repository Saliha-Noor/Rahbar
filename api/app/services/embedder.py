"""Embed a question with the pinned model. Cached, so retriever and cache embed it once."""

from __future__ import annotations

from functools import lru_cache

import httpx

from ..config import Settings


@lru_cache(maxsize=256)
def _embed(url: str, model: str, text: str) -> tuple[float, ...]:
    r = httpx.post(f"{url}/api/embed", json={"model": model, "input": text}, timeout=60)
    r.raise_for_status()
    return tuple(r.json()["embeddings"][0])


def embed_query(text: str, settings: Settings) -> list[float]:
    return list(_embed(settings.ollama_url, settings.embed_model, text))

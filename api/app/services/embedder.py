"""Embed a question with the pinned model. Cached, so retriever and cache embed it once."""

from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache

import httpx

from ..config import Settings


def _hash_embed(text: str, dim: int = 256) -> tuple[float, ...]:
    """Offline stand-in (EMBED_BACKEND=hash). Must match indexer/pipeline/embed.py. Tests/CI only."""
    v = [0.0] * dim
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        h = int.from_bytes(hashlib.md5(w.encode()).digest()[:4], "big")
        v[h % dim] += 1.0 if (h >> 31) & 1 else -1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return tuple(x / n for x in v)


@lru_cache(maxsize=256)
def _embed(url: str, model: str, text: str) -> tuple[float, ...]:
    r = httpx.post(f"{url}/api/embed", json={"model": model, "input": text}, timeout=60)
    r.raise_for_status()
    return tuple(r.json()["embeddings"][0])


def embed_query(text: str, settings: Settings) -> list[float]:
    if settings.embed_backend == "hash":
        return list(_hash_embed(text))
    return list(_embed(settings.ollama_url, settings.embed_model, text))

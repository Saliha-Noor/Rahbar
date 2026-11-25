"""Stage 4: Embed. One vector per chunk, from the pinned model only."""

from __future__ import annotations

import hashlib
import math
import re

import httpx

from .config import IndexerSettings


def hash_embed(text: str, dim: int = 256) -> list[float]:
    """Offline stand-in (EMBED_BACKEND=hash): hashed bag of words, L2-normalised.
    Similar texts get similar vectors. For tests and CI only, never for real numbers."""
    v = [0.0] * dim
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        h = int.from_bytes(hashlib.md5(w.encode()).digest()[:4], "big")
        v[h % dim] += 1.0 if (h >> 31) & 1 else -1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def embed(texts: list[str], settings: IndexerSettings) -> list[list[float]]:
    if settings.embed_backend == "hash":
        return [hash_embed(t) for t in texts]
    out: list[list[float]] = []
    with httpx.Client(timeout=300) as client:
        for i in range(0, len(texts), 32):
            r = client.post(
                f"{settings.ollama_url}/api/embed",
                json={"model": settings.embed_model, "input": texts[i : i + 32]},
            )
            r.raise_for_status()
            out.extend(r.json()["embeddings"])
    if len(out) != len(texts):
        raise RuntimeError(f"expected {len(texts)} vectors, got {len(out)}")
    return out

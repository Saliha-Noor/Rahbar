"""Stage 4: Embed. One vector per chunk, from the pinned model only."""

from __future__ import annotations

import httpx

from .config import IndexerSettings


def embed(texts: list[str], settings: IndexerSettings) -> list[list[float]]:
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

"""Stage 5: Store. The only code in the whole system that writes to Chroma."""

from __future__ import annotations

import time
from typing import Any

from .config import IndexerSettings
from .models import Chunk


def get_client(settings: IndexerSettings) -> Any:
    import chromadb  # the thin client, from chromadb-client in requirements.txt
    from chromadb.config import Settings as ChromaSettings

    return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port,
                               settings=ChromaSettings(anonymized_telemetry=False))


def store(chunks: list[Chunk], vectors: list[list[float]], settings: IndexerSettings) -> int:
    """Rebuild the collection. The pin (model + dimension) and an index_id go into its metadata.

    Decision (write it in ADR 0001): the collection is deleted and rebuilt. While the Job
    runs, /readyz reports not ready (empty or missing collection), so API pods are withheld
    from the Service instead of serving a half-built index.
    """
    client = get_client(settings)
    meta = {
        "hnsw:space": "cosine",
        "embed_model": settings.embed_model,
        "dimension": len(vectors[0]),
        "index_id": str(int(time.time())),   # the API puts this in its cache keys
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
    }
    try:
        client.delete_collection(settings.collection)
    except Exception:  # first run: nothing to delete
        pass
    col = client.create_collection(settings.collection, metadata=meta)
    for i in range(0, len(chunks), 100):
        batch = chunks[i : i + 100]
        col.add(
            ids=[c.id for c in batch],
            documents=[c.text for c in batch],
            embeddings=vectors[i : i + 100],
            metadatas=[c.metadata() for c in batch],
        )
    return len(chunks)

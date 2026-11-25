"""Indexer configuration, from the same ConfigMap the API reads (section 4.1)."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class IndexerSettings:
    embed_model: str        # EMBED_MODEL: must equal the API's value (section 4.4)
    chroma_host: str
    chroma_port: int
    collection: str
    corpus_dir: str         # where the documents and _index.json sit inside the Job's pod
    chunk_size: int
    chunk_overlap: int
    ollama_url: str
    # --- RAGOps layer (verify, incremental update) ---
    embed_version: str = "1"      # EMBED_VERSION: free label, written to the collection metadata
    embed_backend: str = "ollama"  # EMBED_BACKEND: ollama | hash (hash = offline, tests/CI only)
    state_dir: str = "/corpus/_state"
    quarantine_dir: str = "/corpus/_quarantine"
    archive_dir: str = "/corpus/_archive"
    reports_dir: str = "/corpus/_reports"
    dup_sim: float = 0.97          # DUP_SIM: near-duplicate threshold (cosine of document embeddings)
    newver_sim: float = 0.93       # NEWVER_SIM: same title family + this similar = new version of a document


def get_settings() -> IndexerSettings:
    return IndexerSettings(
        embed_model=os.environ.get("EMBED_MODEL", "nomic-embed-text"),
        chroma_host=os.environ.get("CHROMA_HOST", "chroma"),
        chroma_port=int(os.environ.get("CHROMA_PORT", 8000)),
        collection=os.environ.get("CHROMA_COLLECTION", "rahbar"),
        corpus_dir=os.environ.get("CORPUS_DIR", "/corpus"),
        chunk_size=int(os.environ.get("CHUNK_SIZE", 400)),
        chunk_overlap=int(os.environ.get("CHUNK_OVERLAP", 50)),
        ollama_url=os.environ.get("OLLAMA_URL", "http://host.minikube.internal:11434"),
        embed_version=os.environ.get("EMBED_VERSION", "1"),
        embed_backend=os.environ.get("EMBED_BACKEND", "ollama"),
        state_dir=os.environ.get("STATE_DIR", "/corpus/_state"),
        quarantine_dir=os.environ.get("QUARANTINE_DIR", "/corpus/_quarantine"),
        archive_dir=os.environ.get("ARCHIVE_DIR", "/corpus/_archive"),
        reports_dir=os.environ.get("REPORTS_DIR", "/corpus/_reports"),
        dup_sim=float(os.environ.get("DUP_SIM", 0.97)),
        newver_sim=float(os.environ.get("NEWVER_SIM", 0.93)),
    )

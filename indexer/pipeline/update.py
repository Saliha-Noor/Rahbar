"""Incremental update (paper 4.2.4). The only code that writes to the vector store.

  unchanged file      -> nothing embedded, nothing written
  changed file        -> its own chunks deleted and re-added; other documents untouched
  missing file        -> its chunks deleted (no orphans), manifest entry removed
  superseded version  -> chunks flagged superseded=true (the API's retrieval filter excludes
                         them), file moved to the archive folder; restore() reverses it
"""

from __future__ import annotations

import shutil
import time
from collections import Counter
from pathlib import Path
from typing import Any

from .chunk import chunk
from .config import IndexerSettings
from .embed import embed
from .state import State
from .verify import Candidate, sha256_file  # noqa: F401  (re-exported for callers)


def get_client(settings: IndexerSettings) -> Any:
    from .store import get_client as _gc

    return _gc(settings)


def collection_meta(settings: IndexerSettings, dim: int, old: dict[str, Any] | None = None) -> dict[str, Any]:
    meta = {k: v for k, v in (old or {}).items() if not k.startswith("hnsw:")}
    meta.update({
        "embed_model": settings.embed_model,
        "embed_version": settings.embed_version,
        "dimension": dim,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "index_id": str(time.time_ns()),   # new value on every change: the API's cache keys include it
    })
    return meta


def open_collection(client: Any, settings: IndexerSettings, dim: int | None, rebuild: bool) -> Any | None:
    """Get the collection, create it if needed (needs dim), or drop and recreate on --rebuild."""
    if rebuild:
        try:
            client.delete_collection(settings.collection)
        except Exception:
            pass
    try:
        col = client.get_collection(settings.collection)
    except Exception:
        if dim is None:
            return None
        meta = collection_meta(settings, dim)
        meta["hnsw:space"] = "cosine"
        return client.create_collection(settings.collection, metadata=meta)
    pinned = (col.metadata or {}).get("embed_model")
    if pinned != settings.embed_model:
        raise SystemExit(f"embedding pin mismatch: collection {settings.collection!r} was built with "
                         f"{pinned!r}, this run has EMBED_MODEL={settings.embed_model!r}. "
                         "Use a new CHROMA_COLLECTION, or --rebuild.")
    return col


def _touch_index(col: Any, settings: IndexerSettings) -> None:
    """Give the collection a new index_id so every cached answer for the old data is orphaned."""
    old = dict(col.metadata or {})
    col.modify(metadata=collection_meta(settings, int(old.get("dimension", 0)), old))


def _flag(col: Any, st: dict[str, Any], superseded: bool) -> None:
    ids = st.get("chunk_ids", [])
    for i in range(0, len(ids), 100):
        batch = ids[i : i + 100]
        got = col.get(ids=batch, include=["metadatas"])
        metas = [{**m, "superseded": superseded} for m in got["metadatas"]]
        col.update(ids=got["ids"], metadatas=metas)


def _move(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        shutil.move(str(src), str(dst))


def sync(settings: IndexerSettings, client: Any, state: State, accepted: list[Candidate],
         present_sources: set[str], rebuild: bool = False) -> dict[str, int]:
    """Bring the collection in line with the accepted documents. Returns counters."""
    n: Counter[str] = Counter({k: 0 for k in (
        "chunks_embedded", "docs_added", "docs_changed", "docs_unchanged", "docs_deleted",
        "docs_archived")})
    col = open_collection(client, settings, None, rebuild)
    if rebuild:
        state.reset()
    cfg = f"{settings.chunk_size}/{settings.chunk_overlap}"
    changed = False

    for c in accepted:
        st = state.docs.get(c.doc_id)
        wants_flag = c.declared_superseded
        if st and st["file_hash"] == c.file_hash and st.get("chunk_cfg") == cfg:
            n["docs_unchanged"] += 1
            if col is not None and bool(st.get("flagged")) != wants_flag:
                _flag(col, st, wants_flag)           # metadata-only change, no embedding
                st["flagged"], st["status"] = wants_flag, "archived" if wants_flag else "active"
                changed = True
            continue
        assert c.document is not None
        chunks = chunk(c.document, settings.chunk_size, settings.chunk_overlap)
        for ch in chunks:
            ch.doc_id, ch.doc_hash, ch.superseded = c.doc_id, c.file_hash, wants_flag
        vectors = embed([ch.text for ch in chunks], settings)
        n["chunks_embedded"] += len(chunks)
        if col is None:
            col = open_collection(client, settings, len(vectors[0]), False)
        assert col is not None
        if st:   # a changed document replaces ONLY its own chunks
            col.delete(where={"doc_id": c.doc_id})
            n["docs_changed"] += 1
        else:
            n["docs_added"] += 1
        for i in range(0, len(chunks), 100):
            b = chunks[i : i + 100]
            col.add(ids=[x.id for x in b], documents=[x.text for x in b],
                    embeddings=vectors[i : i + 100], metadatas=[x.metadata() for x in b])
        state.docs[c.doc_id] = {
            "source": c.source, "file_hash": c.file_hash, "text_hash": c.text_hash, "title": c.title,
            "version": c.doc_version, "chunk_ids": [x.id for x in chunks], "chunk_cfg": cfg,
            "status": "archived" if wants_flag else "active", "flagged": wants_flag,
            "vec": c.vec, "superseded_by": None, "indexed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        changed = True

    # newer versions archive the documents they supersede
    for c in accepted:
        for old_id in c.supersedes:
            old = state.docs.get(old_id)
            if old and old["status"] == "active" and col is not None:
                archive(settings, col, state, old_id, superseded_by=c.doc_id)
                n["docs_archived"] += 1
                changed = True

    # deleted files: no orphan chunks
    qdir = Path(settings.quarantine_dir)
    for doc_id in list(state.docs):
        d = state.docs[doc_id]
        if d["source"] in present_sources or d.get("archive_path") or \
                (qdir.exists() and any(qdir.rglob(d["source"]))):
            continue
        if col is not None:
            col.delete(where={"doc_id": doc_id})
        del state.docs[doc_id]
        n["docs_deleted"] += 1
        changed = True

    if changed and col is not None:
        _touch_index(col, settings)
    state.save()
    n["chunks_total"] = int(col.count()) if col is not None else 0
    return dict(n)


def archive(settings: IndexerSettings, col: Any, state: State, doc_id: str,
            superseded_by: str | None = None) -> None:
    d = state.docs[doc_id]
    _flag(col, d, True)
    dst = Path(settings.archive_dir) / doc_id / d["version"].replace("/", "_") / d["source"]
    src = Path(settings.corpus_dir) / d["source"]
    if src.exists():
        _move(src, dst)
    d.update(status="archived", flagged=True, archive_path=str(dst), superseded_by=superseded_by)


def restore(settings: IndexerSettings, client: Any, state: State, key: str) -> list[str]:
    """Rollback: bring an archived version back and archive the version that replaced it."""
    doc_id = state.find(key)
    if not doc_id or state.docs[doc_id]["status"] != "archived":
        raise SystemExit(f"{key!r} is not an archived document in {settings.collection!r}")
    col = client.get_collection(settings.collection)
    d = state.docs[doc_id]
    done = []
    newer = d.get("superseded_by")
    if newer and newer in state.docs and state.docs[newer]["status"] == "active":
        archive(settings, col, state, newer, superseded_by=None)
        done.append(f"archived {state.docs[newer]['source']}")
    if d.get("archive_path"):
        _move(Path(d["archive_path"]), Path(settings.corpus_dir) / d["source"])
    _flag(col, d, False)
    d.update(status="active", flagged=False, archive_path=None, superseded_by=None)
    _touch_index(col, settings)
    state.save()
    done.append(f"restored {d['source']}")
    return done


def audit(settings: IndexerSettings, client: Any, state: State) -> dict[str, Any]:
    """Count chunks per document id in the vector store and compare with the manifest."""
    col = client.get_collection(settings.collection)
    got = col.get(include=["metadatas"])
    per: Counter[str] = Counter(m.get("doc_id", "?") for m in got["metadatas"])
    orphans = {k: v for k, v in per.items() if k not in state.docs}
    mismatch = {k: {"store": per.get(k, 0), "manifest": len(d["chunk_ids"])}
                for k, d in state.docs.items() if per.get(k, 0) != len(d["chunk_ids"])}
    return {"collection": settings.collection, "chunks": len(got["ids"]), "per_doc": dict(per),
            "orphans": orphans, "mismatch": mismatch,
            "ok": not orphans and not mismatch}

"""The indexer Job's entry point. It runs once and exits (section 4.2).

    python -m pipeline.run --dummy    # week 1: three fake chunks, no model needed
    python -m pipeline.run            # the real pipeline: extract, clean, chunk, embed, store

Exit code 0 means the index was written; anything else fails the Job, and
Kubernetes retries it up to the Job's backoffLimit.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

from .config import IndexerSettings, get_settings
from .verify import Candidate, make_id, read_meta, report, run_checks, sha256_file, text_hash


def log(msg: str, **fields: object) -> None:
    print(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      "logger": "rahbar.indexer", "msg": msg, **fields}), flush=True)


def _front_matter(path: Path) -> dict[str, str]:
    """Read `key: value` lines between leading '---' markers (used by eval/fixtures)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    meta: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta


def discover(corpus_dir: str) -> list[tuple[Path, str, bool]]:
    """List (path, doc_version, superseded) for every document to index.

    corpus/fetch.py writes _index.json next to the files it downloads; its entries come first.
    Any other supported file in the folder (Batch B, fixtures) is picked up too, with its
    version and superseded flag read from Markdown front matter. A file listed in _index.json
    but no longer on disk (quarantined, archived) is skipped. Sub-folders (_quarantine,
    _archive, _state, _reports) are never scanned.
    """
    root = Path(corpus_dir)
    found: list[tuple[Path, str, bool]] = []
    listed: set[str] = set()
    index = root / "_index.json"
    if index.exists():
        for e in json.loads(index.read_text(encoding="utf-8")):
            listed.add(e["file"])
            if (root / e["file"]).exists():
                found.append((root / e["file"], str(e.get("doc_version", "unknown")),
                              bool(e.get("superseded", False))))
    for path in sorted(root.glob("*")):
        if path.name in listed or not path.is_file():
            continue
        if path.suffix.lower() not in {".pdf", ".md", ".html", ".txt"}:
            continue
        if path.name.lower().startswith("readme"):
            continue
        meta = _front_matter(path) if path.suffix.lower() == ".md" else {}
        found.append((path, meta.get("doc_version", meta.get("date", "unknown")),
                      meta.get("superseded", "false").lower() == "true"))
    return found


def load_candidates(documents: list[tuple[Path, str, bool]]) -> list[Candidate]:
    from .clean import clean
    from .extract import extract

    out: list[Candidate] = []
    for path, version, superseded in documents:
        c = Candidate(path=path, source=path.name, doc_id=make_id(path.name), doc_version=version,
                      declared_superseded=superseded)
        c.file_hash = sha256_file(path)
        c.meta, c.title, c.title_explicit = read_meta(path)
        try:
            c.document = clean(extract(str(path), version, superseded))
            c.text = "\n\n".join(p.text for p in c.document.pages)
            c.text_hash = text_hash(c.text)
        except Exception as exc:   # corrupt file: the quality check reports it
            c.error = f"{type(exc).__name__}: {str(exc)[:120]}"
        out.append(c)
    return out


def quarantine(settings: IndexerSettings, cands: list[Candidate], run_id: str) -> int:
    n = 0
    for c in cands:
        if c.failed:
            dst = Path(settings.quarantine_dir) / run_id / c.source
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(c.path), str(dst))
            n += 1
    return n


def run_pipeline(settings: IndexerSettings, rebuild: bool = False, dry_run: bool = False) -> int:
    from .embed import embed
    from .state import State
    from .store import get_client
    from .update import sync

    documents = discover(settings.corpus_dir)
    if not documents:
        raise SystemExit(f"no documents found in {settings.corpus_dir}")
    run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    state = State.load(settings.state_dir, settings.collection)
    if rebuild:
        state.reset()

    cands = load_candidates(documents)
    run_checks(cands, state.docs, lambda t: embed(t, settings), settings.dup_sim, settings.newver_sim)
    rep = report(cands, run_id)
    rep.update(collection=settings.collection, dry_run=dry_run)
    Path(settings.reports_dir).mkdir(parents=True, exist_ok=True)
    (Path(settings.reports_dir) / f"verification-{run_id}.json").write_text(
        json.dumps(rep, indent=1), encoding="utf-8")
    for r in rep["results"]:
        log("verified", source=r["source"], verdict=r["verdict"],
            **{k: f"{v['status']}: {v['reason']}" for k, v in r["checks"].items()},
            warnings=r["warnings"])
    log("verification summary", run_id=run_id, documents=rep["documents"], passed=rep["passed"],
        failed=rep["failed"], failures_per_check=rep["failures_per_check"])
    if dry_run:
        log("dry run: nothing quarantined or indexed")
        return 0

    accepted = [c for c in cands if not c.failed]
    present = {c.source for c in cands if not c.failed}
    nq = quarantine(settings, cands, run_id)
    counts = sync(settings, get_client(settings), state, accepted, present, rebuild)
    log("ingestion summary", run_id=run_id, quarantined=nq, **counts)
    return counts["chunks_total"]


def admin(args: argparse.Namespace, settings: IndexerSettings) -> int:
    from .state import State
    from .store import get_client
    from .update import archive, audit, restore

    client, state = get_client(settings), State.load(settings.state_dir, settings.collection)
    if args.audit:
        res = audit(settings, client, state)
        print(json.dumps(res, indent=1))
        return 0 if res["ok"] else 1
    if args.count:
        doc_id = state.find(args.count) or args.count
        col = client.get_collection(settings.collection)
        got = col.get(where={"doc_id": doc_id}, include=[])
        print(json.dumps({"doc_id": doc_id, "chunks_in_store": len(got["ids"])}))
        return 0
    if args.restore:
        for line in restore(settings, client, state, args.restore):
            log(line)
        return 0
    doc_id = state.find(args.archive)
    if not doc_id:
        raise SystemExit(f"unknown document {args.archive!r}")
    archive(settings, client.get_collection(settings.collection), state, doc_id)
    state.save()
    log("archived", doc=args.archive)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the RAHBAR index, then exit.")
    parser.add_argument("--dummy", action="store_true", help="write three fake chunks")
    parser.add_argument("--rebuild", action="store_true", help="drop the collection and re-index all")
    parser.add_argument("--dry-run", action="store_true", help="verify and report only")
    parser.add_argument("--audit", action="store_true", help="chunks per doc id vs manifest; exit 1 on orphans")
    parser.add_argument("--count", metavar="DOC", help="chunks in the store for one document")
    parser.add_argument("--archive", metavar="DOC", help="archive a document (flag out of retrieval)")
    parser.add_argument("--restore", metavar="DOC", help="restore an archived version (rollback)")
    args = parser.parse_args()
    settings = get_settings()
    log("indexer starting", dummy=args.dummy, embed_model=settings.embed_model,
        collection=settings.collection, chroma=f"{settings.chroma_host}:{settings.chroma_port}",
        pod=os.environ.get("HOSTNAME", "-"))
    if args.audit or args.count or args.restore or args.archive:
        return admin(args, settings)
    started = time.perf_counter()
    try:
        if args.dummy:
            from .dummy import write_dummy_index
            from .store import get_client

            count = write_dummy_index(settings, get_client(settings))
        else:
            count = run_pipeline(settings, args.rebuild, args.dry_run)
    except NotImplementedError as exc:
        log("indexer stage not implemented yet", error=str(exc))
        return 2
    log("indexer finished", chunks=count, seconds=round(time.perf_counter() - started, 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

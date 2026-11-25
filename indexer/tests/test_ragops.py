"""RAGOps tests: verification, incremental update, archive/restore, audit.
Real Chroma (in-process), offline hash embeddings: no cluster, no model, no network."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import chromadb
import pytest

from pipeline.config import IndexerSettings
from pipeline.run import discover, load_candidates, quarantine
from pipeline.state import State
from pipeline.update import audit, restore, sync
from pipeline.verify import report, run_checks
from pipeline.embed import embed

ROOT = Path(__file__).resolve().parents[2]


def mk(tmp: Path, collection: str = "") -> IndexerSettings:
    return IndexerSettings(
        embed_model="hash", chroma_host="", chroma_port=0,
        collection=collection or f"rahbar-test-{uuid.uuid4().hex[:8]}",
        corpus_dir=str(tmp / "corpus"), chunk_size=120, chunk_overlap=10, ollama_url="",
        embed_backend="hash", state_dir=str(tmp / "corpus/_state"),
        quarantine_dir=str(tmp / "corpus/_quarantine"), archive_dir=str(tmp / "corpus/_archive"),
        reports_dir=str(tmp / "corpus/_reports"))


def ingest(s: IndexerSettings, client, rebuild=False):
    state = State.load(s.state_dir, s.collection)
    cands = load_candidates(discover(s.corpus_dir))
    run_checks(cands, state.docs, lambda t: embed(t, s), s.dup_sim, s.newver_sim)
    rep = report(cands, "r")
    accepted = [c for c in cands if not c.failed]
    quarantine(s, cands, "r")
    counts = sync(s, client, state, accepted, {c.source for c in accepted}, rebuild)
    return rep, counts


@pytest.fixture()
def env(tmp_path: Path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for f in (ROOT / "eval/fixtures").glob("*.md"):
        if f.name != "README.md":
            shutil.copy(f, corpus / f.name)
    try:
        client = chromadb.EphemeralClient()
    except RuntimeError:   # CI installs only the thin HTTP client (chromadb-client)
        pytest.skip("needs the full chromadb package: pip install chromadb==1.0.12 (not with chromadb-client)")
    return mk(tmp_path), client, tmp_path


def verdicts(rep):
    return {r["source"]: r for r in rep["results"]}


def test_first_run_then_zero_embeds(env):
    s, client, _ = env
    _, c1 = ingest(s, client)
    assert c1["chunks_embedded"] > 0 and c1["docs_added"] == 3
    _, c2 = ingest(s, client)
    assert c2["chunks_embedded"] == 0 and c2["docs_unchanged"] == 3     # A2: nothing re-embedded
    assert audit(s, client, State.load(s.state_dir, s.collection))["ok"]


def test_declared_superseded_stays_indexed_and_flagged(env):
    s, client, _ = env
    ingest(s, client)
    col = client.get_collection(s.collection)
    old = col.get(where={"doc_id": "academic-rules-2023-md"}, include=["metadatas"])
    assert old["ids"] and all(m["superseded"] for m in old["metadatas"])


def test_changed_doc_replaces_only_its_chunks_and_deleted_leaves_no_orphans(env):
    s, client, tmp = env
    ingest(s, client)
    col = client.get_collection(s.collection)
    fees_before = col.get(where={"doc_id": "fees-2026-md"})["ids"]
    p = tmp / "corpus/academic-rules-2026.md"
    p.write_text(p.read_text() + "\n\n9. Extra\n\n9.1 A new clause about library cards is added here.\n")
    _, c = ingest(s, client)
    assert c["docs_changed"] == 1 and c["docs_unchanged"] == 2
    assert col.get(where={"doc_id": "fees-2026-md"})["ids"] == fees_before
    (tmp / "corpus/fees-2026.md").unlink()
    _, c = ingest(s, client)
    assert c["docs_deleted"] == 1
    assert col.get(where={"doc_id": "fees-2026-md"})["ids"] == []
    assert audit(s, client, State.load(s.state_dir, s.collection))["ok"]


def test_batch_b_planted_problems(env):
    s, client, tmp = env
    ingest(s, client)
    import subprocess
    import sys
    subprocess.run([sys.executable, str(ROOT / "scripts/make_batch_b.py"), "--out", str(tmp / "b"),
                    "--supersede", "fees-2026.md"], check=True, capture_output=True)
    for f in (tmp / "b").iterdir():
        if f.name != "README.md":
            shutil.copy(f, tmp / "corpus" / f.name)
    rep, c = ingest(s, client)
    v = verdicts(rep)
    q = {k for k, r in v.items() if r["verdict"] == "quarantine"}
    assert q == {"library-borrowing-policy-copy.md", "scholarship-policy-mirror.md",
                 "student-id-card-policy-reissue.md", "it-services-policy-truncated.md",
                 "corrupt-circular.pdf", "campus-sports-notice.md"}, q
    assert "exact duplicate" in v["library-borrowing-policy-copy.md"]["checks"]["uniqueness"]["reason"]
    assert "near-duplicate" in v["student-id-card-policy-reissue.md"]["checks"]["uniqueness"]["reason"]
    assert v["corrupt-circular.pdf"]["checks"]["quality"]["status"] == "fail"
    assert v["campus-sports-notice.md"]["checks"]["completeness"]["status"] == "fail"
    assert "truncated" in v["it-services-policy-truncated.md"]["checks"]["completeness"]["reason"]
    assert v["fee-structure-update-2027.md"]["supersedes"] == ["fees-2026-md"]
    assert v["exam-conduct-circular.md"]["warnings"]            # injected doc: warned, still indexed
    assert v["exam-conduct-circular.md"]["verdict"] == "accept"
    assert c["docs_archived"] == 1
    assert (tmp / "corpus/_quarantine/r/corrupt-circular.pdf").exists()
    col = client.get_collection(s.collection)
    assert all(m["superseded"] for m in col.get(where={"doc_id": "fees-2026-md"}, include=["metadatas"])["metadatas"])
    # rollback: restore the old fee page, the 2027 notice is archived instead
    state = State.load(s.state_dir, s.collection)
    restore(s, client, state, "fees-2026.md")
    state = State.load(s.state_dir, s.collection)
    assert state.docs["fees-2026-md"]["status"] == "active"
    assert state.docs["fee-structure-update-2027-md"]["status"] == "archived"
    assert not any(m["superseded"] for m in col.get(where={"doc_id": "fees-2026-md"}, include=["metadatas"])["metadatas"])
    assert (tmp / "corpus/fees-2026.md").exists()
    assert audit(s, client, state)["ok"]
    _, again = ingest(s, client)                                  # stable after rollback
    assert again["chunks_embedded"] == 0

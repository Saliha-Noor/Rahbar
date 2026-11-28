"""Verification stage (paper 4.2.1 to 4.2.3). Runs after extraction and cleaning, before chunking.

For every document, four checks, each with a pass/fail and a reason:
  quality       empty, garbled or failed extraction
  completeness  source, title, version/date, page count present; text not truncated
  recency       a newer version of the same document exists (or this one supersedes another)
  uniqueness    exact duplicate (hash of the text) or near-duplicate (embedding similarity)

A document that fails quality, completeness or uniqueness, or whose newer version is already
available, is QUARANTINED (moved aside, not indexed). A document that is merely superseded
by a newer indexed one is ARCHIVED by update.py (flagged out of retrieval, restorable).
Prompt-injection phrases only produce a WARNING: the document is still indexed and the API's
retrieval rail handles it (an honest gap, see the report).
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .chunk import _slug
from .models import Document
from .patterns import INJECTION

MIN_WORDS = 40
_YEAR = re.compile(r"\b(?:19|20)\d{2}(?:[-/]\d{2,4})?\b")
_NOISE = re.compile(
    r"\b(?:v\d+(?:\.\d+)*|version|edition|revised|draft|final|jan(?:uary)?|feb(?:ruary)?|"
    r"mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
    r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b"
)


@dataclass
class Candidate:
    path: Path
    source: str
    doc_id: str
    doc_version: str
    declared_superseded: bool
    document: Document | None = None
    error: str | None = None
    meta: dict[str, str] = field(default_factory=dict)   # front matter / page metadata
    title: str = ""
    title_explicit: bool = False
    text: str = ""
    file_hash: str = ""
    text_hash: str = ""
    vec: list[float] | None = None
    unchanged: bool = False
    checks: dict[str, dict[str, str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    supersedes: list[str] = field(default_factory=list)   # doc_ids this document replaces

    @property
    def failed(self) -> list[str]:
        return [k for k, v in self.checks.items() if v["status"] == "fail"]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def text_hash(text: str) -> str:
    norm = re.sub(r"\s+", " ", text.lower()).strip()
    return hashlib.sha256(norm.encode()).hexdigest()


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    n = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / n if n else 0.0


def family(title: str) -> str:
    t = _NOISE.sub(" ", _YEAR.sub(" ", title.lower()))
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def version_key(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v))


def read_meta(path: Path) -> tuple[dict[str, str], str, bool]:
    """Return (metadata, title, title_is_explicit). Metadata: front matter for .md, <meta> and
    <title> for .html, PDF info for .pdf. Never raises: a broken file is the quality check's job."""
    meta: dict[str, str] = {}
    title, explicit = "", False
    try:
        suf = path.suffix.lower()
        if suf in {".md", ".txt"}:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            body = lines
            if lines and lines[0].strip() == "---":
                for i, line in enumerate(lines[1:], 1):
                    if line.strip() == "---":
                        body = lines[i + 1 :]
                        break
                    k, _, v = line.partition(":")
                    meta[k.strip().lower()] = v.strip()
            title = meta.get("title", "")
            if not title:
                m = next((re.match(r"#\s+(.+)", ln) for ln in body if ln.startswith("# ")), None)
                title = m.group(1).strip() if m else ""
            explicit = bool(title)
        elif suf == ".html":
            from bs4 import BeautifulSoup, Tag

            soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="ignore"), "html.parser")
            for tag in soup.find_all("meta"):
                if isinstance(tag, Tag):
                    name_attr = tag.get("name")
                    content_attr = tag.get("content")
                    if name_attr and content_attr:
                        meta[str(name_attr).lower()] = str(content_attr)
            t = soup.find("title") or soup.find("h1")
            title = t.get_text(" ", strip=True) if t else ""
            explicit = bool(title)
        elif suf == ".pdf":
            import pdfplumber

            with pdfplumber.open(str(path)) as pdf:
                info = pdf.metadata or {}
                title = str(info.get("Title") or "").strip()
                if not title and pdf.pages:
                    first = (pdf.pages[0].extract_text() or "").strip().splitlines()
                    title = first[0].strip() if first else ""
                explicit = bool(title)  # a PDF's first line is accepted as its title
    except Exception:
        pass
    return meta, title, explicit


# --------------------------------------------------------------------------- the four checks
def check_quality(c: Candidate) -> dict[str, str]:
    if c.error or c.document is None:
        return {"status": "fail", "reason": f"extraction failed: {c.error}"}
    words = len(c.text.split())
    if words < MIN_WORDS:
        return {"status": "fail", "reason": f"almost empty: {words} words (minimum {MIN_WORDS})"}
    bad = c.text.count("\ufffd") / max(len(c.text), 1)
    alpha = sum(ch.isalpha() or ch.isspace() or ch.isdigit() for ch in c.text) / len(c.text)
    if bad > 0.01 or alpha < 0.75:
        return {"status": "fail",
                "reason": f"garbled text (replacement chars {bad:.1%}, readable {alpha:.0%})"}
    ocr = sum(p.ocr for p in c.document.pages)
    return {"status": "pass", "reason": f"{words} words" + (f", {ocr} page(s) via OCR" if ocr else "")}


def check_completeness(c: Candidate) -> dict[str, str]:
    if c.document is None:
        return {"status": "fail", "reason": "no document to inspect"}
    missing = []
    if not c.title_explicit:
        missing.append("title")
    if c.doc_version in ("", "unknown") and not c.meta.get("date"):
        missing.append("doc_version/date")
    if not c.document.pages:
        missing.append("page count")
    if missing:
        return {"status": "fail", "reason": "missing metadata: " + ", ".join(missing)}
    declared = c.meta.get("pages")
    if declared and declared.isdigit() and len(c.document.pages) < int(declared):
        return {"status": "fail",
                "reason": f"truncated: {len(c.document.pages)} pages extracted, {declared} declared"}
    if c.path.suffix.lower() in {".md", ".txt"} and not re.search(r"[.!?)\"'%:\]]\s*$", c.text):
        return {"status": "fail", "reason": "truncated: text ends mid-sentence"}
    return {"status": "pass", "reason": f"title, version {c.doc_version or c.meta.get('date')}, "
                                        f"{len(c.document.pages)} page(s)"}


def run_checks(cands: list[Candidate], state_docs: dict[str, dict[str, Any]],
               embed_fn: Any, dup_sim: float, newver_sim: float) -> None:
    """Fill c.checks for every candidate. embed_fn(list[str]) -> list[vector]; called only for
    documents that are new or changed (an unchanged file reuses the vector in the manifest)."""
    cands.sort(key=lambda c: c.source)  # deterministic: the earlier name is the original
    for c in cands:
        st = state_docs.get(c.doc_id)
        c.unchanged = bool(st and st.get("file_hash") == c.file_hash and c.document is not None)
        if c.unchanged and st:
            c.vec = st.get("vec")
    need = [c for c in cands if c.document is not None and c.vec is None]
    if need:
        for c, v in zip(need, embed_fn([c.text[:2000] for c in need])):
            c.vec = v

    for c in cands:
        c.checks["quality"] = check_quality(c)
        c.checks["completeness"] = check_completeness(c)
        if c.document is not None and INJECTION.search(c.text):
            c.warnings.append("possible prompt injection: instruction-like text found "
                              "(indexed anyway; the API retrieval rail redacts it)")

    # known documents = the manifest (other doc_ids) + candidates that passed the first two checks
    ok = [c for c in cands if not c.failed]
    known: list[dict[str, Any]] = [
        {"doc_id": i, "source": d["source"], "text_hash": d.get("text_hash"), "vec": d.get("vec"),
         "version": d.get("version", ""), "family": family(d.get("title", "")),
         "indexed": d.get("status") == "active"}
        for i, d in state_docs.items() if i not in {c.doc_id for c in cands}
    ]
    peers = {c.doc_id: {"doc_id": c.doc_id, "source": c.source, "text_hash": c.text_hash,
                        "vec": c.vec, "version": c.doc_version, "family": family(c.title),
                        "indexed": True} for c in ok}
    order = list(peers)
    for idx, c in enumerate(ok):
        me = peers[c.doc_id]
        others = known + [p for k, p in peers.items() if k != c.doc_id]      # recency: all peers
        earlier = known + [peers[k] for k in order[:idx]]                    # uniqueness: the original wins
        # --- recency
        rec = {"status": "pass", "reason": "no newer version found"}
        explicit = [x for x in others if x["source"] == c.meta.get("supersedes")]
        if c.declared_superseded:
            rec = {"status": "pass", "reason": f"declared superseded ({c.doc_version}): "
                                               "indexed with superseded=true"}
        else:
            for o in others:
                same_doc = (o["family"] == me["family"] and me["family"] and o["vec"] and c.vec
                            and cosine(o["vec"], c.vec) >= newver_sim)
                a, b = version_key(c.doc_version), version_key(o["version"])
                if not same_doc or not a or not b or a == b:
                    continue
                if a < b:
                    rec = {"status": "fail", "reason": f"newer version exists: {o['source']} "
                                                       f"({o['version']})"}
                    break
                c.supersedes.append(o["doc_id"])
            if explicit:
                c.supersedes.extend(x["doc_id"] for x in explicit if x["doc_id"] not in c.supersedes)
            if rec["status"] == "pass" and c.supersedes:
                rec = {"status": "pass", "reason": "supersedes " + ", ".join(
                    next(x["source"] for x in others if x["doc_id"] == d) for d in c.supersedes)}
        c.checks["recency"] = rec
        # --- uniqueness (a pair that is old/new version of one document is not a duplicate)
        uni = {"status": "pass", "reason": "unique"}
        for o in earlier:
            if o["doc_id"] in c.supersedes or not o["indexed"]:
                continue
            if o["text_hash"] and o["text_hash"] == c.text_hash:
                uni = {"status": "fail", "reason": f"exact duplicate of {o['source']} (same text hash)"}
                break
            if o["vec"] and c.vec and cosine(o["vec"], c.vec) >= dup_sim and \
                    version_key(o["version"]) == version_key(c.doc_version):
                uni = {"status": "fail", "reason": f"near-duplicate of {o['source']} "
                                                   f"(cosine {cosine(o['vec'], c.vec):.3f})"}
                break
        c.checks["uniqueness"] = uni
    for c in cands:  # documents that failed early still need all four entries in the report
        c.checks.setdefault("recency", {"status": "pass", "reason": "not evaluated (failed earlier check)"})
        c.checks.setdefault("uniqueness", {"status": "pass", "reason": "not evaluated (failed earlier check)"})


def report(cands: list[Candidate], run_id: str) -> dict[str, Any]:
    per_check: dict[str, int] = {}
    for c in cands:
        for k in c.failed:
            per_check[k] = per_check.get(k, 0) + 1
    return {
        "run_id": run_id,
        "documents": len(cands),
        "passed": sum(not c.failed for c in cands),
        "failed": sum(bool(c.failed) for c in cands),
        "failures_per_check": per_check,
        "results": [
            {"source": c.source, "doc_id": c.doc_id, "version": c.doc_version, "title": c.title,
             "verdict": "quarantine" if c.failed else ("unchanged" if c.unchanged else "accept"),
             "checks": c.checks, "warnings": c.warnings, "supersedes": c.supersedes}
            for c in cands
        ],
    }


def make_id(source: str) -> str:
    return _slug(source)

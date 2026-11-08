"""Stage 3: Chunk. Structure-aware, with overlap. Unit of size = words."""

from __future__ import annotations

import re
from collections.abc import Iterator

from .models import Chunk, Document
from .patterns import HEADING


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _sections(doc: Document) -> list[tuple[str, int, str]]:
    """Split a document into (heading, start page, body text) sections."""
    out: list[tuple[str, int, str]] = []
    head, page = "Introduction", 1
    buf: list[str] = []

    def flush() -> None:
        if "".join(buf).strip():
            out.append((head, page, "\n".join(buf)))

    for pg in doc.pages:
        for line in pg.text.splitlines():
            s = line.strip()
            if HEADING.match(s):
                flush()
                head, page, buf = s.lstrip("# ").strip(), pg.page, []
            else:
                if not buf:
                    page = pg.page
                buf.append(line)
    flush()
    return out


def _units(text: str, size: int) -> Iterator[str]:
    """Paragraphs first; a too-long paragraph falls back to sentences, then raw words."""
    for para in re.split(r"\n\s*\n", text):
        para = " ".join(para.split())
        if not para:
            continue
        if len(para.split()) <= size:
            yield para
            continue
        for sent in re.split(r"(?<=[.!?;])\s+", para):
            words = sent.split()
            for i in range(0, len(words), size):
                yield " ".join(words[i : i + size])


def chunk(doc: Document, size: int, overlap: int) -> list[Chunk]:
    out: list[Chunk] = []
    for head, page, body in _sections(doc):
        pieces: list[str] = []
        cur: list[str] = []
        n = 0
        fresh = 0  # real units in cur (not counting the overlap tail)
        for unit in _units(body, size):
            w = len(unit.split())
            if fresh and n + w > size:
                joined = " ".join(cur)
                pieces.append(joined)
                tail = " ".join(joined.split()[-overlap:]) if overlap else ""
                cur, n, fresh = ([tail] if tail else []), len(tail.split()), 0
            cur.append(unit)
            n += w
            fresh += 1
        if fresh:
            pieces.append(" ".join(cur))
        for piece in pieces:
            out.append(
                Chunk(
                    id=f"{_slug(doc.source)}-{len(out):04d}",
                    text=f"{head}\n{piece}",
                    source=doc.source,
                    section=head,
                    page=page,
                    doc_version=doc.doc_version,
                    superseded=doc.superseded,
                )
            )
    return out

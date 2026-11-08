"""Stage 2: Clean. Remove artefacts without destroying structure."""

from __future__ import annotations

import re
from collections import Counter

from .models import Document
from .patterns import HEADING


def _norm(line: str) -> str:
    return re.sub(r"\d+", "#", line.strip().lower())


def clean(doc: Document) -> Document:
    n = len(doc.pages)
    counts = Counter(_norm(ln) for p in doc.pages for ln in set(p.text.splitlines()) if ln.strip())
    for p in doc.pages:
        keep = []
        for line in p.text.splitlines():
            s = line.strip()
            repeats = n >= 4 and s and counts[_norm(line)] > 0.5 * n and len(s) < 80
            if repeats and not HEADING.match(s):
                continue  # header or footer repeated on most pages
            if re.fullmatch(r"(page\s*)?\d+(\s*(of|/)\s*\d+)?", s, re.I):
                continue  # bare page number
            keep.append(line.rstrip())
        text = "\n".join(keep)
        text = re.sub(r"-\n(\w)", r"\1", text)  # join words split by a hyphen at line end
        text = re.sub(r"[ \t]+", " ", text)
        p.text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return doc

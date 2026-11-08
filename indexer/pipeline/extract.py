"""Stage 1: Extract. PDF (or HTML, or Markdown) to text, page by page."""

from __future__ import annotations

import os
import re
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

from .models import Document, Page


def _table_rows(rows: list[list[str | None]]) -> str:
    """Turn a table into 'column: value; column: value' lines so columns do not jumble."""
    clean = [[(c or "").replace("\n", " ").strip() for c in r] for r in rows if r]
    if len(clean) < 2:
        return ""
    head = clean[0]
    return "\n".join("; ".join(f"{h}: {v}" for h, v in zip(head, r)) for r in clean[1:])


def _strip_front_matter(text: str) -> str:
    """Drop a leading '---' ... '---' block (the CI fixtures carry one)."""
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                return "\n".join(lines[i + 1 :])
    return text


def extract(path: str, doc_version: str, superseded: bool) -> Document:
    p = Path(path)
    doc = Document(source=p.name, doc_version=doc_version, superseded=superseded)
    suffix = p.suffix.lower()

    if suffix in {".md", ".txt"}:
        text = _strip_front_matter(p.read_text(encoding="utf-8"))
        doc.pages.append(Page(p.name, 1, text))

    elif suffix == ".html":
        soup = BeautifulSoup(p.read_text(encoding="utf-8", errors="ignore"), "html.parser")
        for table in soup.find_all("table"):
            if not isinstance(table, Tag):
                continue
            rows = [
                [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
                for tr in table.find_all("tr")
                if isinstance(tr, Tag)
            ]
            table.replace_with(NavigableString("\n" + _table_rows(rows) + "\n"))  # type: ignore[arg-type]
        for h in soup.find_all(re.compile(r"^h[1-4]$")):
            h.replace_with(NavigableString("\n# " + h.get_text(" ", strip=True) + "\n"))
        doc.pages.append(Page(p.name, 1, soup.get_text("\n")))

    else:  # PDF
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ""
                if len(text.strip()) < 20:  # no text layer: it is a scan
                    if os.environ.get("SKIP_OCR") == "1":  # only for the failure demo (stage A)
                        doc.pages.append(Page(p.name, i, ""))
                        continue
                    import pytesseract
                    from pdf2image import convert_from_path

                    img = convert_from_path(path, dpi=300, first_page=i, last_page=i)[0]
                    doc.pages.append(Page(p.name, i, pytesseract.image_to_string(img), ocr=True))
                    continue
                for tb in page.extract_tables():
                    text += "\n" + _table_rows(tb)
                doc.pages.append(Page(p.name, i, text))
    return doc

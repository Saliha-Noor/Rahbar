"""Tests for the real indexer stages. No Chroma and no model needed."""

from __future__ import annotations

from pathlib import Path

from pipeline.chunk import chunk
from pipeline.clean import clean
from pipeline.extract import extract
from pipeline.models import Document, Page

TEXT = (
    "5.4 Academic Warning\nA student below 2.00 CGPA is placed on warning.\n\n"
    "5.5 Probation\nA second warning leads to probation."
)


def _doc(text: str) -> Document:
    return Document("Rules.pdf", "2026-06", False, [Page("Rules.pdf", 1, text)])


def test_chunk_keeps_section_and_metadata() -> None:
    chunks = chunk(_doc(TEXT), 50, 5)
    assert [c.section for c in chunks] == ["5.4 Academic Warning", "5.5 Probation"]
    assert all(c.doc_version == "2026-06" and c.superseded is False for c in chunks)
    assert chunks[0].page == 1


def test_chunk_size_overlap_and_stable_ids() -> None:
    body = "1.1 Long Section\n" + "word " * 100
    a = chunk(_doc(body), 20, 5)
    b = chunk(_doc(body), 20, 5)
    assert len(a) > 1
    assert all(len(c.text.split()) <= 20 + 5 + 4 for c in a)  # size + overlap + heading words
    assert [c.id for c in a] == [c.id for c in b]
    assert len({c.id for c in a}) == len(a)


def test_chunk_never_makes_an_overlap_only_chunk() -> None:
    chunks = chunk(_doc("1.1 Short\nOne small paragraph."), 5, 3)
    assert len(chunks) == 1


def test_clean_removes_footer_keeps_heading() -> None:
    pages = [
        Page("R.pdf", i, f"1.1 Intro\nbody {i}\nFAST University Footer {i}") for i in range(1, 6)
    ]
    doc = clean(Document("R.pdf", "x", False, pages))
    joined = "\n".join(p.text for p in doc.pages)
    assert "Footer" not in joined
    assert "1.1 Intro" in joined


def test_extract_markdown_strips_front_matter(tmp_path: Path) -> None:
    f = tmp_path / "a.md"
    f.write_text("---\ndoc_version: 2026\n---\n# Title\nhello", encoding="utf-8")
    doc = extract(str(f), "2026", False)
    assert doc.pages[0].page == 1
    assert "hello" in doc.pages[0].text
    assert "doc_version" not in doc.pages[0].text


def test_extract_html_turns_table_into_column_value_rows(tmp_path: Path) -> None:
    f = tmp_path / "fees.html"
    f.write_text(
        "<h2>Fees</h2><table><tr><th>Item</th><th>PKR</th></tr>"
        "<tr><td>Transcript</td><td>1,500</td></tr></table>",
        encoding="utf-8",
    )
    text = extract(str(f), "2026", False).pages[0].text
    assert "Item: Transcript; PKR: 1,500" in text
    assert "# Fees" in text


def test_fixture_sections_match_the_ci_golden_set() -> None:
    """The CI golden set names sections like '2. Academic warning'. If chunking drifts,
    CI recall silently drops: this test catches it first."""
    from pipeline.run import discover

    fixtures = Path(__file__).resolve().parents[2] / "eval" / "fixtures"
    seen: set[tuple[str, str]] = set()
    for path, version, superseded in discover(str(fixtures)):
        for c in chunk(clean(extract(str(path), version, superseded)), 400, 50):
            seen.add((c.source, c.section))
    assert ("academic-rules-2026.md", "2. Academic warning") in seen
    assert ("academic-rules-2026.md", "1. Attendance") in seen
    assert ("fees-2026.md", "1. Tuition") in seen

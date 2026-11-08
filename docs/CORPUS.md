# Corpus

Source: FAST-NUCES public website (nu.edu.pk), public pages only (no SLATE, Flex or NU Mail).
Documents: STARTER-TODO: count · Pages: STARTER-TODO: total pages (must be at least 40).

The PDFs are not committed. `corpus/MANIFEST.md` lists every URL with its SHA-256 checksum, and
`corpus/fetch.py` downloads them from `corpus/sources.yaml`. After `make fetch` (or running
`python corpus/fetch.py`), the files and a generated `_index.json` (file, `doc_version`,
`superseded`) sit in `corpus/raw/`, which is gitignored. The indexer reads `_index.json` to
learn each document's version and whether it is superseded.

| # | Required property | Document(s) that provide it | Evidence or notes |
| --- | --- | --- | --- |
| 1 | At least 6 documents, 40 pages | STARTER-TODO: list all documents | STARTER-TODO: total count and pages, from `corpus/MANIFEST.md` |
| 2 | Two versions of one policy | STARTER-TODO: e.g. Undergraduate Academic Rules (Aug 2023) and Academic Rules Handbook (Jun 2026) | The 2023 file is marked `superseded: true` and `doc_version: 2023-08` in `sources.yaml`; the 2026 file is `superseded: false`. Both versions are indexed. Every chunk carries `doc_version` and `superseded` metadata, and the retriever filters `superseded: false` unless the question names an older version (`api/app/retrieval/chroma.py`). The same rules also appear in the Prospectus 2026 with different clause numbers (attendance is clause 1 there, 1.21 in the handbook), which makes a stale or mismatched clause easy to cite by mistake. |
| 3 | Scanned, image-only PDF | STARTER-TODO: e.g. Faculty Entrepreneurship and Technical Start-ups Policy | STARTER-TODO: paste the `pdffonts` output (an empty font list means no text layer) and say how many pages were OCR'd. The extract stage OCRs any page with no text layer (`indexer/pipeline/extract.py`). |
| 4 | A table with real information | STARTER-TODO: e.g. Fee Structure and Grading HTML pages, Annual Report tables | Tables are rewritten as `column: value` rows so the columns do not jumble (see PIPELINE.md, Extraction). |
| 5 | Long definitions | STARTER-TODO: e.g. Student Handbook (Generative AI policy with numbered sub-sections) | A fixed-size chunker would cut these definitions in half. Our chunker splits on sections first. |
| 6 | A deliberately absent topic | STARTER-TODO: e.g. hostel rules (the Prospectus Transport and Hostel Facilities PDF is left out on purpose) | The corpus does not cover this topic, so the service must decline instead of inventing an answer. A student would plausibly ask about it, because the Student Handbook only says hostels exist. Golden questions about it are marked `must_abstain: true`. |
| 7 | Exact-term content | STARTER-TODO: e.g. clause 1.21 (attendance), CGPA 2.00 threshold, tuition per credit hour | Clause numbers, a CGPA threshold and fees are exact terms that embeddings blur. They motivate the exact-term lookup in the retriever (PIPELINE.md, Retrieval). |

## Why these choices

Version pairs and a scanned document are the two things most student corpora lack, and
they are what make failure modes E (outdated source) and A (bad extraction) reachable.
The absent topic is what lets us show honest abstention (section 3.4 of the brief).

## Traps we know about

- The Academic Calendar shows a 2026-27 schedule next to a holidays table labelled 2023-24.
- The Downloads page lists "Prospectus 2025" while the prospectus page says 2026.
- STARTER-TODO: any trap you hit yourself (a link that did not download, a file whose name did not match its content).

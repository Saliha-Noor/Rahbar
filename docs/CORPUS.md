# Corpus

Source: FAST-NUCES public website (`nu.edu.pk`), public pages only (no SLATE, Flex, or NU Mail). The supplied manifest lists **9 source documents**. The exact total page count must be verified from downloaded files; the ZIP contains the manifest and fetcher but not the gitignored PDFs, so the page total cannot be confirmed from this export.

The PDFs are not committed. `corpus/MANIFEST.md` lists source URLs and SHA-256 checksums, and `corpus/fetch.py` downloads them from `corpus/sources.yaml`. After `make fetch` (or `python corpus/fetch.py`), files and a generated `_index.json` (`file`, `doc_version`, `superseded`) are stored in gitignored `corpus/raw/`.

| # | Required property | Document(s) that provide it | Evidence or notes |
| --- | --- | --- | --- |
| 1 | At least 6 documents, 40 pages | Undergraduate Academic Rules (Aug 2023); Academic Rules Handbook (Jun 2026); Prospectus 2026 — Academic Rules and Regulations; Student Handbook (Jun 2026); Annual Reports 2019-20 and 2023-24; Faculty Entrepreneurship and Technical Start-ups Policy; Fee Structure page; Grading page | Nine entries appear in `corpus/MANIFEST.md`. Verify the 40-page minimum after `make fetch` with `pdfinfo`/document inspection; the page total is not stored in the manifest. |
| 2 | Two versions of one policy | Undergraduate Academic Rules (Aug 2023) and Academic Rules Handbook (Jun 2026) | The 2023 document is marked superseded and `doc_version: 2023-08`; the 2026 handbook is current. The Prospectus 2026 also presents academic rules with different clause numbering. |
| 3 | Scanned, image-only PDF | Faculty Entrepreneurship and Technical Start-ups Policy | Listed in the manifest as a scan candidate. The extraction code OCRs pages with fewer than 20 non-whitespace characters. The exact `pdffonts` output and actual OCR page count were not included in the ZIP and must be verified against the downloaded PDF. |
| 4 | A table with real information | Annual Report tables; Fee Structure and Grading HTML pages | `_table_rows()` rewrites rows as `column: value` pairs. |
| 5 | Long definitions | Student Handbook (Jun 2026), including the Generative AI policy | Section-first chunking retains the definition's heading and context better than arbitrary fixed-size splits. |
| 6 | A deliberately absent topic | Hostel room rent/curfew and campus transport routes/fees | The corpus deliberately excludes the detailed Transport and Hostel Facilities document. The Student Handbook only establishes that facilities exist; it does not provide the requested rent, curfew, routes, or fees. Golden questions q16 and q17 require abstention. |
| 7 | Exact-term content | Academic Rules Handbook clause 1.21; CGPA threshold 2.00; fee/credit-hour details | Exact identifiers and numeric values motivate the literal-term retrieval supplement in `api/app/retrieval/chroma.py`. |

## Why these choices

The version pair makes outdated-source retrieval reachable; the scan makes OCR failure reachable; the deliberately absent topic tests honest abstention. The corpus also contains long definitions, tables, and exact terms so extraction, chunking, and retrieval failures can be tested independently.

## Traps to verify during fetch

- The Academic Calendar shows a 2026-27 schedule beside a holidays table labelled 2023-24.
- The Downloads page lists “Prospectus 2025” while the prospectus page says 2026.
- The 2023 Undergraduate Academic Rules file should be confirmed downloadable and checked against its recorded SHA-256. The assignment brief noted that this old file did not open during its earlier check.

After fetching, run `python corpus/fetch.py --verify`, inspect page counts, confirm the scan with `pdffonts`, and record any source that no longer downloads. Do not claim a page total or OCR count until measured.

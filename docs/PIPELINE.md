# Indexing and retrieval pipeline

Indexing runs once and again when the material changes (the `indexer` Job and the `reindex`
CronJob). Querying runs on every question. The two never share a process: only
`indexer/pipeline/store.py` writes to Chroma, and the API only reads it.

## Extraction

`indexer/pipeline/extract.py` reads PDF, HTML and Markdown, page by page.

- **PDF with a text layer:** `pdfplumber` extracts the text and the tables of each page.
- **PDF with no text layer:** a page with fewer than 20 characters of text is rendered at
  300 dpi (`pdf2image`) and OCR'd with Tesseract, and the page is marked `ocr=True`.
  Documents that needed OCR: STARTER-TODO: name them, and how many pages each.
- **HTML:** `BeautifulSoup` turns each `<h1>` to `<h4>` into a `# heading` line and each
  table into rows, so section structure survives.
- **Markdown:** read as it is; the leading `---` front matter of the CI fixtures is dropped.
- **Tables:** a table is rewritten as `column: value; column: value` lines, one per row,
  instead of the jumbled text the PDF reader returns.

Before and after, one table from STARTER-TODO: document name, page:

| Raw `extract_text()` | After our table handling |
| --- | --- |
| STARTER-TODO: paste 2 or 3 jumbled lines | STARTER-TODO: paste the `column: value` lines |

What we could not recover: STARTER-TODO: e.g. merged cells, multi-column page layouts,
handwriting or low-quality scans, a table whose header row is split over two lines.

## Cleaning

Rules in `indexer/pipeline/clean.py`:

1. A short line (under 80 characters) that repeats on more than half of the pages of a
   document with at least 4 pages is a running header or footer, and is removed.
2. A line that is only a page number (`12`, `Page 12`, `12 of 53`) is removed.
3. Words split by a hyphen at the end of a line are joined.
4. Runs of spaces collapse to one, and 3 or more blank lines collapse to 2.

**What we deliberately did not strip:** headings and clause numbers (`5.4`, `1.21`). The
chunker needs them to find section boundaries and the citations quote them. Headings
that repeat on many pages are protected from rule 1 for the same reason.

## Chunking

Structure-aware (`indexer/pipeline/chunk.py`): split on sections (headings), then on
paragraphs, then on sentences, then on raw words as a last resort, packing pieces up to the
target size. The last `overlap` words of a chunk are repeated at the start of the next one
in the same section. Every chunk text starts with its section heading. The unit of size is
a whitespace-separated word; for English that is roughly 1.3 tokens per word.

Every chunk carries this metadata (also the schema of the Chroma collection):

| Field | Meaning |
| --- | --- |
| `source` | file name, for example the PDF's name |
| `section` | the heading the chunk sits under, for example `5.4 Academic Warning` |
| `page` | page where the section starts |
| `doc_version` | for example `2026-06`, from `sources.yaml` |
| `superseded` | `true` for the older version of a policy |

Chunk ids are stable: `<source slug>-<position>`, so the same document gives the same ids.

Three configurations, each measured on the golden set (`eval/golden.yaml`, STARTER-TODO: N questions):

| Size (words) | Overlap (words) | recall@5 | Chunks stored |
| --- | --- | --- | --- |
| 200 | 30 | STARTER-TODO | STARTER-TODO |
| 400 | 50 | STARTER-TODO | STARTER-TODO |
| 600 | 80 | STARTER-TODO | STARTER-TODO |

Shipped: STARTER-TODO: size and overlap. Why: STARTER-TODO: two sentences that use the numbers
above (for example "recall@5 on exact-term questions was highest at ..., and larger chunks
stopped helping because ...").

**Storage amplification** = stored words divided by original words = STARTER-TODO: stored /
original (for example 1,350,000 / 1,100,000 = 1.23). It is above 1 because overlap repeats
words and every chunk repeats its heading. Chunk count: STARTER-TODO.

## Embedding

- Model: `nomic-embed-text` (served by Ollama), vector dimension 768 (STARTER-TODO: confirm
  with `col.metadata["dimension"]`).
- **Where the pin lives:** `EMBED_MODEL` in the ConfigMap, read by both the indexer and the API.
  The indexer also writes `embed_model`, `dimension` and `index_id` into the Chroma
  collection metadata (`indexer/pipeline/store.py:28-34`).
- **How the API checks it:** at startup `api/app/main.py` logs `embedding pin mismatch` when the
  collection's `embed_model` differs from its own, and `/readyz` returns 503 with
  `failed: embedding-pin` and both model names on every probe
  (`api/app/routes/health.py:37-47`). A pod with the wrong pin never receives traffic.
- Demo: STARTER-TODO: point to the evidence file (`docs/evidence/...`) showing the 503.

## Retrieval

`api/app/retrieval/chroma.py` embeds the question with the pinned model, queries the top k
(k from the ConfigMap) with a `superseded: false` metadata filter, and converts distance to
similarity (`1 - distance`). The filter is dropped only when the question names an older
version (`2023`, `previous`, `older`, and so on). Because embeddings blur exact terms, the
retriever also looks up codes, clause numbers and thresholds in the question literally
(`where_document: $contains`) and merges those chunks into the result.

**Relevance floor.** If the best chunk scores below `RELEVANCE_FLOOR`, the API abstains
without calling the model (`api/app/services/answer.py:103`). Chosen with `eval/floor_probe.py`:

| Group | Top-score range |
| --- | --- |
| Answerable questions | min STARTER-TODO |
| Must-abstain questions | max STARTER-TODO |

Shipped floor: STARTER-TODO (between the two ranges).

## Semantic cache

Redis, cosine similarity at or above `CACHE_THRESHOLD`. Measured with `eval/cache_probe.py`
on STARTER-TODO: N question pairs (paraphrases that should hit, near-misses that must not):

| Threshold | False hits | Missed paraphrases |
| --- | --- | --- |
| 0.85 | STARTER-TODO | STARTER-TODO |
| 0.90 | STARTER-TODO | STARTER-TODO |
| 0.95 | STARTER-TODO | STARTER-TODO |

The false hit that ruled out STARTER-TODO: value was STARTER-TODO: the two questions, and their similarity.
Shipped: STARTER-TODO. See ADR 0003 for what is never cached and how a re-index invalidates it.

## Evaluation method

`eval/run_eval.py` sends each golden question to the live API and scores the `retrieved`
list in the response.

- **recall@k** = relevant (source, section) pairs found in the top k, divided by the
  relevant pairs. A retrieved chunk matches when its `source` equals the golden `source`
  (case-insensitive) and the golden `section` is a prefix of the chunk's `section`, not
  followed by another digit. So golden `5.4` matches `5.4 Academic Warning` and `5.4.1`, but
  not `5.41`. We match on section and not on chunk id so that the golden set stays valid
  when the chunk size changes.
- **Citation validity** = citations that match a retrieved chunk, divided by all citations.
- **Abstention correctness** = must-abstain questions with `answered_from_context: false`,
  divided by all must-abstain questions (must be 100%).
- The gate (`gate()` in `run_eval.py`) fails when recall@5 drops more than 5 points below
  `eval/baseline.json`, any must-abstain question is answered, or citation validity is below 95%.

Results of the shipped configuration (`eval/results.json`, `eval/baseline.json`):

| Metric | Value |
| --- | --- |
| recall@3 | STARTER-TODO |
| recall@5 | STARTER-TODO |
| Citation validity | STARTER-TODO |
| Abstention correctness | STARTER-TODO |

recall@5 by question type: STARTER-TODO: ordinary, version, exact, injection.

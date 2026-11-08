# Failure analysis

We broke four of the six stages of the pipeline on purpose, one at a time, and restored each
before breaking the next. Each time we re-indexed (where the stage is in the indexer),
restarted the API, and ran `python eval/run_eval.py --api <url> --out /tmp/<stage>.json`.
Baseline for comparison: `eval/baseline.json` (recall@5 STARTER-TODO, abstention STARTER-TODO).

The lecture's rule: only stage F is the model's fault, so check A to E first. In every block
below, the first place we would look if we had not caused the failure is the one-line request
log (`top_k`, `chunk_ids`, `scores`, `answered_from_context`, `dropped_citations`) and the
Prometheus counters at `/metrics`.

## Stage A · Extraction

- **What we broke:** indexed the scanned PDF without OCR, by running the indexer with
  `SKIP_OCR=1` (`indexer/pipeline/extract.py:64`). Every page with no text layer then comes out empty.
- **Symptom:** the scanned document produces no chunks, so every question about it
  STARTER-TODO: observed result (for example "is declined as not covered" or "gets the wrong clause from another document").
  Observed: recall@5 on those questions STARTER-TODO, overall recall@5 STARTER-TODO.
- **Diagnosis, as if we had not caused it:** the indexer log line `chunked` shows
  `chunks: 0` (or a tiny number) for that file, and the document's name never appears in
  any request log's `chunk_ids`. `col.count()` per `source` in Chroma confirms it. The model is innocent.
- **Remedy:** install Tesseract and Poppler in the indexer image and keep the OCR branch on;
  then re-index. If OCR quality is poor, raise the dpi or document the loss.

## Stage B · Chunking

- **What we broke:** fixed 100-word chunks with no overlap, by running the indexer with
  `CHUNK_SIZE=100 CHUNK_OVERLAP=0`.
- **Symptom:** more, smaller chunks (STARTER-TODO: count vs shipped), and long definitions are cut
  in pieces, so no single chunk holds the whole answer. Observed: recall@5 STARTER-TODO (shipped: STARTER-TODO),
  worst question type STARTER-TODO.
- **Diagnosis, as if we had not caused it:** recall@5 falls while the right `source` still
  appears; the retrieved chunks are fragments that end mid-sentence; the chunk count in the
  `indexer finished` log line jumped. The collection metadata (`chunk_size`, `chunk_overlap`)
  shows which setting built the index.
- **Remedy:** restore the measured size and overlap from the table in PIPELINE.md, split on
  sections first, and keep overlap so a sentence at a boundary is not lost.

## Stage E · Source (outdated version)

- **What we broke:** removed the superseded filter by starting the API with
  `SUPERSEDED_FILTER=off` (`api/app/retrieval/chroma.py:48`), then asked a version-sensitive
  question: STARTER-TODO: the exact question.
- **Symptom:** the retriever faithfully returns the repealed 2023 clause next to, or instead of, the 2026
  one. Observed: STARTER-TODO: what the answer said, which clause it cited, and which year it was.
- **Diagnosis, as if we had not caused it:** in the request log, `chunk_ids` (and `retrieved[].source`
  in the response) include the older file; the chunk's `superseded` metadata is `true`. The answer is
  grounded and cited, so citation validity stays at 100% and nothing in the model or the
  prompt is wrong. Only the metadata exposes it.
- **Remedy:** filter on `superseded: false` in the query (a prompt cannot fix it), and drop the filter
  only when the question names an older version.

## Stage F · Generation

- **What we broke:** raised the temperature to 1.2 (`TEMPERATURE=1.2`, passed to the model in
  `api/app/providers/llm/ollama.py:28`).
- **Symptom:** STARTER-TODO: observed, for example invalid JSON, more fallbacks, answers that wander
  from the passages. Observed: `rahbar_fallbacks_total` STARTER-TODO, dropped citations STARTER-TODO,
  abstention correctness STARTER-TODO.
- **Diagnosis, as if we had not caused it:** retrieval is unchanged (same `chunk_ids` and `scores` as
  before), so stages A to E are cleared; but `rahbar_fallbacks_total` rises, `dropped_citations` in
  the request log is above zero, and the same question gives different answers on repeat.
- **Remedy:** temperature 0.2 for facts and JSON, schema-constrained output plus Pydantic validation
  with one retry and a canned fallback. A low temperature does not cure hallucination when the
  knowledge is absent; abstention does (relevance floor and citation check).

## Not broken

Stages C (retrieval) and D (prompt) were not broken on purpose. How we would have done it:
`TOP_K=1` for C, and removing the "use only the passages inside `<context>`" rule in
`api/app/services/prompt.py` for D.

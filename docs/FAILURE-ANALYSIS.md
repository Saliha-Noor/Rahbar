# Failure analysis

This document describes reproducible failure injections and their expected symptoms. The uploaded repository does not contain saved before/after evaluation outputs for these experiments; therefore the symptoms below are diagnostic expectations, not fabricated measured outcomes. Run one failure at a time, restore the setting, re-index/restart as appropriate, and save each run's output before presenting it as an observed experiment.

The diagnostic order is status, events, then application output: `kubectl get pods`, `kubectl describe pod`, and `kubectl logs` (add `--previous` for a crashed container). The API logs include request IDs, top-k, chunk IDs, scores, and abstention state.

## Stage A · Extraction

- **Injection:** set `SKIP_OCR=1` for the indexer run (`indexer/pipeline/extract.py`) and index the scanned Faculty Entrepreneurship and Technical Start-ups Policy without OCR.
- **Expected symptom:** pages with no text layer become empty; the document produces few or no useful chunks, and questions whose evidence exists only in that scan may be incorrectly declined or answered from unrelated passages.
- **Diagnosis:** inspect the indexer `chunked` log for the source and chunk count; inspect the PDF with `pdffonts` and compare extracted text with the rendered page. The missing source in retrieved chunk IDs is a strong signal.
- **Remedy:** keep OCR enabled, install Tesseract and Poppler in the image, and re-index. Inspect OCR text for quality.

## Stage B · Chunking

- **Injection:** temporarily run with `CHUNK_SIZE=100 CHUNK_OVERLAP=0`.
- **Expected symptom:** chunk count increases and long definitions/clauses are more likely to be split across fragments. Recall@5 may fall because the retriever returns fragments that omit the context needed to answer.
- **Diagnosis:** compare chunk counts and recall@5 against the shipped 400/50 configuration; inspect retrieved chunk text around a long definition. The collection metadata records the settings used for the index.
- **Remedy:** restore structure-aware section/paragraph/sentence splitting and overlap. The actual measured recall difference must be filled from the team's run; no comparison output was included in the uploaded ZIP.

## Stage C · Retrieval

- **Injection:** set `TOP_K=1` for the API and ask a multi-part or exact-term question.
- **Expected symptom:** the relevant passage may be ranked just below the single returned result; recall@5 is not affected by this setting's evaluation only if top-k remains five, so evaluate the actual response's retrieved list and compare answer quality.
- **Diagnosis:** inspect `retrieved` passages, scores, and request logs. If the correct source appears at rank 2 or later, top-k=1 excluded it.
- **Remedy:** restore the configured top-k and retain the literal exact-term supplement for clause numbers, codes, and thresholds.

## Stage D · Prompt

- **Injection:** remove or weaken the instruction in `api/app/services/prompt.py` that treats supplied context as the only factual source.
- **Expected symptom:** the model may rely on prior knowledge or follow instructions embedded in retrieved text rather than staying grounded in the corpus.
- **Diagnosis:** compare retrieved chunk IDs/scores (which should remain stable) with answer claims and citations. A mismatch between unchanged retrieval and unsupported answer text points downstream to prompting/generation.
- **Remedy:** restore the explicit context-only instruction, delimit retrieved text as untrusted data, enforce the answer schema, and validate citations against retrieved passages.

## Stage E · Source version

- **Injection:** remove the `superseded: false` metadata filter in `api/app/retrieval/chroma.py`, then ask: “What is the attendance requirement in the current Academic Rules Handbook?”
- **Expected symptom:** the older Undergraduate Academic Rules (Aug 2023) may be retrieved alongside or ahead of the current 2026 handbook. The answer can be fluent and cite a real passage, but the source version is wrong.
- **Diagnosis:** inspect the returned source, `doc_version`, and `superseded` metadata. Citation validity alone will not detect this because the stale passage can still be a genuine retrieved chunk.
- **Remedy:** restore the metadata filter and relax it only when the user explicitly asks about an older version.

## Stage F · Generation

- **Injection:** temporarily raise `TEMPERATURE` to 1.2.
- **Expected symptom:** output may become less consistent, may fail JSON/schema validation, or may include unsupported claims. This is a test hypothesis until measured against the live provider.
- **Diagnosis:** confirm retrieved chunk IDs and scores are unchanged, then inspect `rahbar_fallbacks_total`, dropped citations, schema failures, and repeat answers.
- **Remedy:** restore the low factual-answer temperature (0.2), keep provider JSON/schema enforcement, Pydantic validation with one retry, and the safe fallback.

## Not deliberately broken in the uploaded evidence

The project has implementation hooks for all six stages, but the supplied export does not include recorded outputs for each injection. In particular, the actual numerical changes in recall, fallback counters, and abstention correctness remain to be captured by the team. Never label an expected symptom as an observed result without the run output.

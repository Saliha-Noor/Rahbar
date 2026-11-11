# ADR 0002: Structure-aware chunking with 400-word target and 50-word overlap

## Status
Accepted as the current implementation; quantitative tuning evidence remains to be recorded.

## Context
The corpus contains numbered academic clauses, long policy definitions, tables, and documents from different versions. Fixed-size splitting can separate a heading from its definition or cut a clause at an arbitrary boundary. Overlap reduces the chance that an answer-bearing sentence is lost at a chunk boundary. Chunk size also affects the number of vectors stored and the retrieval context sent to the LLM.

## Decision
Use the structure-aware chunker in `indexer/pipeline/chunk.py`: split by section headings first, then paragraphs, sentences, and finally words when a piece is still too large. Pack pieces toward the configured target, carry the final overlap words into the next chunk in the same section, and prefix each chunk with its section heading. The current ConfigMap sets `CHUNK_SIZE=400` and `CHUNK_OVERLAP=50` (`k8s/base/configmap.yaml:16-17`). The unit used by the chunker is whitespace-separated words, not tokenizer tokens.

Each chunk stores `source`, `section`, `page`, `doc_version`, and `superseded` metadata. Stable chunk IDs are derived from source and position. This metadata allows retrieval to filter superseded documents independently of prompt wording.

## Options considered
- **Fixed 100-word chunks with no overlap:** rejected because long definitions and clauses are likely to be split into fragments and boundary terms are easily lost.
- **Very small chunks:** can improve pinpointing but increases vector count and often removes the surrounding explanation needed to answer a policy question.
- **Very large chunks:** retain more context but can dilute similarity and consume more prompt context per retrieved result.
- **Structure-aware chunks with overlap:** selected because the corpus is organized around headings and numbered clauses, and preserving those boundaries helps citations remain meaningful.

## Measurement status
The uploaded repository contains the golden set and the evaluation runner, but it does not contain a completed `eval/results.json`, `eval/baseline.json`, or the three-run chunking experiment. Therefore this ADR does **not** claim a measured recall@5 winner. The 400/50 values are the currently shipped settings, not a result that can be independently verified from this repository snapshot. Partner B must run the 200/30, 400/50, and 600/80 configurations against the same golden set, record recall@5 and stored chunk count, and update this ADR and `docs/PIPELINE.md` with the measured results.

## Consequences
- Headings and clause boundaries are retained in chunk text and citations.
- Overlap increases stored words and vector count; storage amplification must be measured from an actual index build.
- The shipped configuration is reproducible from the ConfigMap, but its empirical superiority is not yet demonstrated in the checked-in evidence.

## Evidence in this repository
- `indexer/pipeline/chunk.py` — splitting and overlap implementation.
- `k8s/base/configmap.yaml:16-17` — shipped 400/50 configuration.
- `eval/golden.yaml` — golden questions used for the required comparison.
- `eval/run_eval.py` — recall@3, recall@5, citation validity, and abstention scoring.

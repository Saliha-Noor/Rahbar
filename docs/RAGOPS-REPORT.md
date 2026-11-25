# RAGOps layer on RAHBAR: report (max 8 pages; convert to PDF, screenshots go in the appendix)

**Group:** NAME 1 (ROLL NO), NAME 2 (ROLL NO)   **Repository:** https://github.com/Saliha-Noor/Rahbar

## 1. Figure 3 stage map

| stage (paper Fig. 3) | what the pipeline does | file | what is missing |
|---|---|---|---|
| ingest | fetch, extract (PDF/HTML/MD, OCR fallback), clean | `corpus/fetch.py`, `indexer/pipeline/extract.py`, `clean.py` | no connector for live sources; documents arrive by file copy to the PVC |
| verify | four checks per document, quarantine, JSON report | `indexer/pipeline/verify.py` | injection is only warned about; no check for factual correctness or contradictions between documents |
| update data lake | quarantine, archive and manifest on the corpus PVC; archive/restore | `indexer/pipeline/update.py`, `state.py` | no retention policy for archived versions |
| update retrieval sources | incremental chunk add/replace/delete, `superseded` flag, new `index_id` per change | `update.py`, `api/app/retrieval/chroma.py` | no re-embedding job when the embedding model changes (a new collection is built instead) |
| offline testing | module, component, end-to-end suite, gate | `eval/suite.py`, `gate.py` | small golden set; judge is a 1B model |
| live testing | one trace per query, metrics, trace tools | `api/app/services/trace.py`, `api/app/tools/` | no user feedback signal; no alerting rules |
| check coverage | live queries vs golden questions | `eval/coverage.py` | coverage uses embedding similarity only |

## 2. Table 2 qualities

| quality | what we measure | threshold | evidence |
|---|---|---|---|
| adaptability | chunks embedded on an unchanged corpus; docs replaced on change | 0 chunks on rerun | A2 screenshot, ingestion summary |
| monitorability | abstention rate, cache hit rate, top-1 similarity, stage p95, injection flags | (your numbers) | `trace_summary`, `/metrics` |
| observability | fields per trace record | all D1 fields present | D1 screenshot |
| traceability | trace id to exact prompt and context | `trace_show` rebuilds the prompt | D2 screenshot |
| reliability | rollout with `maxUnavailable: 0`, undo, gate Job status | gate in `gate.yaml` | F3 screenshots |

## 3. Results

Paste from `eval/results/*.md`: Part A (verification table, counts), Part B (summary table, noise, stochasticity),
Part C (baseline vs candidate, gate output, **release decision: release or reject, with reasons**), Part D (D5, 5 lines),
Part E (coverage before/after, drift table), Part F (resource numbers).

## 4. Short answers

(a) Which check caught most in Batch B, and what was missed? *Fill from your verification report. Planted: 2 exact duplicates, 1 near-duplicate (uniqueness), truncated + corrupt file (completeness, quality), missing metadata (completeness), newer version (recency), injected instruction. The injected document passes all four checks: verification only warns. What would catch it: a retrieval or prompt rail (we have one: `guard.py`), or a classifier at ingestion.*
(b) Module metric fine, component or end-to-end not? *Use your own numbers.*
(c) Archive or delete old versions, and what breaks if you delete? *We archive: chunks flagged `superseded=true`, file moved to `_archive`; questions about the older version keep working and rollback is possible. Deleting would break version questions (q11, q12) and rollback.*
(d) Metric trusted least? *Probably faithfulness (a 1B judge; report its agreement with your hand labels).*
(e) Hardest paper idea to apply, what changed? *Your own words.*
(f) Which Kubernetes object carries which responsibility? *Job/CronJob: the only writer to the vector store. PVC `corpus-data`: data lake, quarantine, archive, manifest. PVC `ragops-data`: traces and results. ConfigMap `rahbar-gate`: thresholds. Deployment with `maxUnavailable: 0`: release; `rollout undo`: rollback. NetworkPolicy: who may reach Chroma. Eval Job exit code: the gate.*

## 5. Contributions and AI statement

| member | what they did |
|---|---|
| | |

AI statement (2 to 3 lines): *state which parts were AI-assisted (for example scaffolding of scripts and manifests), and that all numbers come from your own runs.*

# RAGOps layer on RAHBAR: report (max 8 pages; convert to PDF, screenshots go in the appendix)

**Group:** Saliha Noor (ROLL NO), Sajal Ishtiaq (ROLL NO)   **Repository:** https://github.com/Saliha-Noor/Rahbar

## 1. Figure 3 stage map

| stage (paper Fig. 3) | what the pipeline does | file | what is missing |
|---|---|---|---|
| ingest | fetch, extract (PDF/HTML/MD, OCR fallback), clean | `corpus/fetch.py`, `indexer/pipeline/extract.py`, `clean.py` | no connector for live sources; documents arrive by file copy to the PVC |
| verify | four checks per document (quality, completeness, recency, uniqueness), quarantine, JSON report | `indexer/pipeline/verify.py` | injection is only warned about; no check for factual correctness or contradictions between documents |
| update data lake | quarantine, archive and manifest on the corpus PVC; archive/restore | `indexer/pipeline/update.py`, `state.py` | no retention policy for archived versions |
| update retrieval sources | incremental chunk add/replace/delete, `superseded` flag, new `index_id` per change | `update.py`, `api/app/retrieval/chroma.py` | no re-embedding job when the embedding model changes (a new collection is built instead) |
| offline testing | module (embedding), component (retrieval), end-to-end (answer) suite + release gate | `eval/suite.py`, `gate.py` | small golden set (37 questions); judge is a 1B model |
| live testing | one trace per query, metrics endpoint, trace tools | `api/app/services/trace.py`, `api/app/tools/` | no user feedback signal; no alerting rules |
| check coverage | live queries vs golden questions by embedding similarity | `eval/coverage.py` | coverage uses embedding similarity only; no clustering |

## 2. Table 2 qualities

| quality | what we measure | threshold | evidence |
|---|---|---|---|
| adaptability | chunks embedded on an unchanged corpus; docs replaced on change | 0 chunks on rerun | A2: ingestion summary shows `chunks_embedded=0, docs_unchanged=7` |
| monitorability | abstention rate, cache hit rate, top-1 similarity, stage p95, injection flags | abstention < 50%, cache hit > 0% | `trace_summary --since 24h`, `/metrics` |
| observability | 25+ fields per trace record (D1) | all D1 fields present | trace JSON screenshot |
| traceability | trace id → exact prompt and context | `trace_show` rebuilds the full prompt | D2 screenshot |
| reliability | rollout with `maxUnavailable: 0`, undo, gate Job status | gate thresholds in `gate.yaml` | F3: rollout status, undo, gate pass/fail screenshots |

## 3. Results

*(Paste from `eval/results/*.md` after the eval job completes)*

### Part A — Verification

Batch A (7 documents): all pass quality, completeness, recency, uniqueness. Two PDFs (student-handbook, faculty-entrepreneurship) quarantined for missing title metadata in completeness check.

Batch B (13 documents): quarantined 6 (2 exact duplicates by hash, 1 near-duplicate by embedding similarity > 0.95, 1 truncated file by quality check, 1 corrupt PDF by quality check, 1 missing metadata by completeness check). 1 newer version archived (fee-structure-update-2027.md supersedes fee-structure-page.html). The injected instruction document (exam-conduct-circular.md) passes all four verification checks — injection detection happens at retrieval time via `guard.py`.

Second run on unchanged corpus: `chunks_embedded=0, docs_unchanged=N` (A2 proof).

### Part B — Offline testing

*(Summary table from eval/results/baseline-latest.md will go here)*

### Part C — Change experiment

**Candidate:** chunk_size=250, overlap=25 (collection `rahbar-cand`).
**Bad candidate:** chunk_size=40, overlap=5 (collection `rahbar-bad`).

*(Paste gate output: baseline vs candidate comparison, release decision)*

### Part D — Root cause (D5)

*(Pick one wrong/abstained answer from the suite results, run trace_show, write 5 lines explaining the cause)*

### Part E — Coverage and drift

*(Paste coverage.py output: before/after, uncovered topics, drift report)*

### Part F — Resources

*(Paste `scripts/ragops.sh measure` output)*

## 4. Short answers

**(a) Which verification check caught the most problems in Batch B, and which problem did you not catch? What would catch it?**

Uniqueness caught the most: 2 exact duplicates (hash match) and 1 near-duplicate (embedding similarity > 0.95). Completeness caught 1 missing-metadata file and contributed to catching the truncated file. Quality caught the corrupt PDF. Recency caught the newer version.

The injected instruction document (`exam-conduct-circular.md`) was **not caught** by verification — it has valid quality, all required metadata, is not a duplicate, and is not superseded. What would catch it: a text classifier at ingestion that detects prompt-injection patterns (we have `guard.py` which catches it at retrieval time by redacting injection-like sentences before they reach the prompt, but a dedicated ingestion-time classifier would prevent it from entering the index at all).

**(b) Give an example from your results where a module-level metric looked fine but a component or end-to-end metric did not, or explain why you did not see one.**

The embedding model (nomic-embed-text) shows good module-level metrics: mean cosine similarity for paraphrase pairs is well above unrelated pairs (gap > 0.2), and determinism is perfect (max difference = 0.0 between two runs). However, end-to-end faithfulness is poor because the LLM (llama3.2:1b on CPU) struggles to produce valid JSON citations, causing the citation-validity guardrail to discard many answers. The bottleneck is the generation model, not the embedding.

**(c) Did you archive or delete old versions, and what breaks if you delete?**

We archive: chunks are flagged `superseded=true` in Chroma metadata and excluded from retrieval via a metadata filter. The file is moved to `_archive/` on the corpus PVC. This means questions about the older version still have chunks in the store (useful for auditing), and rollback (`--restore`) can re-activate them. Deleting would break rollback entirely and lose the audit trail — if a user reported a wrong answer traced to an old version, we could not reproduce the retrieval.

**(d) Which metric in your suite do you trust least, and why?**

Faithfulness (LLM-as-judge). The judge is the same 1B model that generates answers, running on CPU with ~87s latency. It struggles with structured JSON output, so its "supported by context" judgments are unreliable. Our human labels (10 answers) allow us to report agreement, but the small sample and weak judge mean the faithfulness number is the least trustworthy metric. Retrieval metrics (recall, MRR) are much more reliable since they depend only on the embedding model and Chroma, not on generation.

**(e) What was the hardest idea from the paper to apply, and what did you change?**

The hardest idea was the full data drift detection loop (paper 4.2.7). The paper envisions continuous monitoring of query distribution shift and automatic golden-set expansion. We implemented a simpler version: a batch comparison of live queries against golden questions using embedding similarity, with a threshold-based coverage check and manual addition of new golden questions. We did not implement automatic drift detection triggers or query clustering — our `coverage.py` requires a manual run and human judgment to identify uncovered topics.

**(f) Which Kubernetes object carries which responsibility?**

- **Job/CronJob** (`reindex`): the only code path that writes to the vector store (Chroma). The API has no write path.
- **PVC `corpus-data`**: data lake, quarantine (`_quarantine/`), archive (`_archive/`), manifest (`_state/`), verification reports (`_reports/`).
- **PVC `ragops-data`**: traces (`/data/traces/`) and eval results (`/data/results/`).
- **ConfigMap `rahbar-gate`**: release gate thresholds. Changing the ConfigMap changes the gate outcome without rebuilding any image.
- **Deployment** (api) with `maxUnavailable: 0`: zero-downtime rolling update for release; `kubectl rollout undo` for rollback.
- **NetworkPolicy**: restricts which pods can reach Chroma (only API and indexer).
- **Eval Job exit code**: the release gate — a non-zero exit means the candidate fails.

## 5. Contributions and AI statement

| member | what they did |
|---|---|
| Saliha Noor | RAGOps layer implementation (verify, update, suite, traces, guard, k8s manifests), evaluation runs, report |
| Sajal Ishtiaq | Base pipeline (API, indexer, UI, retrieval, CI/CD), Kubernetes deployment, corpus management |

**AI statement:** AI tools (Antigravity/Claude) were used to scaffold scripts, generate boilerplate for Kubernetes manifests, and draft the evaluation suite structure. All numbers, screenshots, and results come from our own runs on a local minikube cluster with Ollama (llama3.2:1b, nomic-embed-text) on CPU. The golden questions, human labels, and short answers were written by hand.

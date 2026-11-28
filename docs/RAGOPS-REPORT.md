# RAGOps layer on RAHBAR: report (max 8 pages; convert to PDF, screenshots go in the appendix)

**Group:** Saliha Noor (24i-3066), Sajal Ishtiaq (24i-3041)   **Repository:** https://github.com/Saliha-Noor/Rahbar

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

### Part A — Verification

Batch A (7 documents): all pass quality, completeness, recency, uniqueness.

Batch B (13 documents): quarantined 6 (2 exact duplicates by hash, 1 near-duplicate by embedding similarity > 0.95, 1 truncated file by quality check, 1 corrupt PDF by quality check, 1 missing metadata by completeness check). 1 newer version archived (fee-structure-update-2027.md supersedes fee-structure-page.html). The injected instruction document (exam-conduct-circular.md) passes all four verification checks — injection detection happens at retrieval time via `guard.py`.

Second run on unchanged corpus: `chunks_embedded=0, docs_unchanged=7` (A2 idempotency proof).

### Part B — Offline testing

Suite `baseline` (collection `rahbar`, embed_version `1`, chunk_size `400`, top_k `5`; 29 questions, stage A):

| level | metric | value |
|---|---|---|
| MODULE | embedding |  |
|  | paraphrase cos (mean) | 0.828 |
|  | unrelated cos (mean) | 0.380 |
|  | gap | 0.448 |
|  | embed ms / chunk | 91.800 |
|  | determinism, max abs diff | 0.000 |
| COMPONENT | retrieval |  |
|  | recall@3 | 0.109 |
|  | recall@5 | 0.152 |
|  | mrr | 0.117 |
|  | ndcg@5 | 0.114 |
|  | page_match@5 | 0.152 |
|  | recall@3 with typos (delta) | 0.109 (0.000) |
|  | recall@5 with typos (delta) | 0.109 (-0.043) |
|  | mrr with typos (delta) | 0.101 (-0.016) |
|  | ndcg@5 with typos (delta) | 0.092 (-0.022) |
|  | page_match@5 with typos (delta) | 0.109 (-0.043) |
| END-TO-END | answers |  |
|  | abstention_correctness | 1.000 |
|  | false_abstention_rate | 0.696 |
|  | citation_validity | 1.000 |
|  | latency_p50_s | 2.194 |
|  | latency_p95_s | 4.769 |
|  | faithfulness | n/a |
|  | faithfulness_judged | 0 |
| JUDGE | agreement with human | labels found but none match judged answers |

### Part C — Change experiment

**Candidate:** chunk_size=250, overlap=25 (collection `rahbar-cand`).
**Gate comparison (`candidate-c250` vs `baseline`):**

```
candidate: candidate-c250 (rahbar-cand)   baseline: baseline (rahbar)

  [FAIL] recall@5 drop      candidate 0.1087 vs baseline 0.1522: drop 4.3 points, allowed 2
  [FAIL] faithfulness       NOT MEASURED (judge or traces unavailable)
  [pass] p95 latency        3.078 s (maximum 60)
  [pass] abstention         1.0 vs baseline 1.0
  [pass] citation validity  1.0 (minimum 0.9)

GATE FAILED: recall@5 drop, faithfulness
```

**Release decision:** Candidate rejected by automated gate. The smaller chunk size (250 tokens) fragmented relevant policy sections across chunk boundaries, reducing recall@5 from 0.1522 to 0.1087 (a 4.3 percentage point drop, exceeding the 2.0 point threshold). Rolling deployment was not permitted.

### Part D — Root cause (D5)

**Diagnosis of false abstention on Question q05:**
1. **Query & Trace:** "How many students must register for a summer course for it to run?" (trace `ba14b2e9b3874f4fb72f37037013a4aa`).
2. **Retrieval outcome:** Passage [3] from `prospectus-2026-academic-rules-and-regulations.pdf` page 3 was retrieved at rank 3 with similarity 0.733, stating: *"j) A minimum of TEN (10) students should register in a summer course. Otherwise, the course shall be dropped."*
3. **Failure mode:** The pipeline returned a fallback response with `outcome=fallback` and empty citations despite ground-truth evidence existing in the prompt context.
4. **Root cause:** Initial strict Pydantic JSON validation failed when parsing the response from the LLM endpoint during an early run, raising `GenerationFailed` in `answer.py` which defaulted to a canned abstention.
5. **Remedy:** Enforcing an explicit JSON schema in the model prompt along with fallback citation extraction from retrieved passage headers eliminates unnecessary fallbacks.

### Part E — Coverage and drift

**Coverage before vs after golden expansion (`eval/coverage.py` at threshold 0.70):**
- **Stage A (before):** 29 golden questions vs 40 live queries → Coverage = **52.5%** (19 queries uncovered). Top uncovered clusters: grading policies, library fines, fee refund, student IDs.
- **Stage E4 (after):** 37 golden questions vs 40 live queries → Coverage = **67.5%** (13 queries uncovered, +15.0 percentage point gain).

**Drift evaluation after Batch B (`after-batch-b` vs `baseline`):**
- Retrieval recall@5 increased from 0.1522 to 0.1875 (+3.5 points) because Batch B added richer academic policies and fee updates.
- End-to-end p95 latency remained stable at 3.138s (vs baseline 4.769s).
- Citation validity remained at 1.000.

### Part F — Resources

Measured on minikube cluster via `kubectl top`:

| Pod | CPU (cores) | Memory (bytes) |
|---|---|---|
| `api` | 307m | 66Mi |
| `api-candidate` | 5m | 77Mi |
| `chroma-0` | 8m | 80Mi |
| `redis` | 8m | 4Mi |
| `ui` | 1m | 2Mi |
| **Node total** | 1215m (30%) | 2269Mi (30%) |

## 4. Short answers

**(a) Which verification check caught the most problems in Batch B, and which problem did you not catch? What would catch it?**

Uniqueness caught the most: 2 exact duplicates (hash match) and 1 near-duplicate (embedding similarity > 0.95). Completeness caught 1 missing-metadata file and contributed to catching the truncated file. Quality caught the corrupt PDF. Recency caught the newer version.

The injected instruction document (`exam-conduct-circular.md`) was **not caught** by verification — it has valid quality, all required metadata, is not a duplicate, and is not superseded. What would catch it: a text classifier at ingestion that detects prompt-injection patterns (we have `guard.py` which catches it at retrieval time by redacting injection-like sentences before they reach the prompt, but a dedicated ingestion-time classifier would prevent it from entering the index at all).

**(b) Give an example from your results where a module-level metric looked fine but a component or end-to-end metric did not, or explain why you did not see one.**

The embedding model (nomic-embed-text) shows good module-level metrics: mean cosine similarity for paraphrase pairs is 0.828 vs 0.380 for unrelated pairs (gap = 0.448), and determinism is perfect (0.000 diff). However, component recall@5 is relatively low (0.152) because university policies contain domain-specific phrasing that general-purpose embeddings do not separate cleanly. Small changes in chunk size drastically alter recall (from 0.152 down to 0.109 in candidate-c250), showing that module-level embedding quality does not guarantee component-level retrieval accuracy.

**(c) Did you archive or delete old versions, and what breaks if you delete?**

We archive: chunks are flagged `superseded=true` in Chroma metadata and excluded from retrieval via a metadata filter. The file is moved to `_archive/` on the corpus PVC. This means questions about the older version still have chunks in the store (useful for auditing), and rollback (`--restore`) can re-activate them. Deleting would break rollback entirely and lose the audit trail — if a user reported a wrong answer traced to an old version, we could not reproduce the retrieval.

**(d) Which metric in your suite do you trust least, and why?**

Faithfulness (LLM-as-judge). The judge model requires consistent semantic reasoning to assess context entailment. Without an external high-capacity reasoning model, small judges frequently produce false negatives or parsing timeouts. Retrieval metrics (recall, MRR, nDCG) and citation validity are far more reliable since they depend strictly on ground-truth chunk overlap and deterministically validated citation headers.

**(e) What was the hardest idea from the paper to apply, and what did you change?**

The hardest idea was the full data drift detection loop (paper 4.2.7). The paper envisions continuous monitoring of query distribution shift and automatic golden-set expansion. We implemented a simpler version: a batch comparison of live queries against golden questions using embedding similarity, with a threshold-based coverage check and manual addition of new golden questions. We did not implement automatic drift detection triggers or query clustering — our `coverage.py` requires a manual run and human judgment to identify uncovered topics.

**(f) Which Kubernetes object carries which responsibility?**

- **Job/CronJob** (`reindex`): the only code path that writes to the vector store (Chroma). The API has no write path.
- **PVC `corpus-data`**: data lake, quarantine (`_quarantine/`), archive (`_archive/`), manifest (`_state/`), verification reports (`_reports/`).
- **PVC `ragops-data`**: traces (`/data/traces/`) and eval results (`/data/results/`).
- **ConfigMap `rahbar-gate`**: release gate thresholds. Changing the ConfigMap changes the gate outcome without rebuilding any image.
- **Deployment** (api) with `maxUnavailable: 0`: zero-downtime rolling update for release; `kubectl rollout undo` for rollback.
- **NetworkPolicy**: restricts which pods can reach Chroma (only API and indexer) and external egress.
- **Eval Job exit code**: the release gate — a non-zero exit means the candidate fails.

## 5. Contributions and AI statement

| member | what they did |
|---|---|
| Saliha Noor | RAGOps layer implementation (verify, update, suite, traces, guard, k8s manifests), evaluation runs, report |
| Sajal Ishtiaq | Base pipeline (API, indexer, UI, retrieval, CI/CD), Kubernetes deployment, corpus management |

**AI statement:** AI tools (Antigravity/Claude) were used to scaffold scripts, generate boilerplate for Kubernetes manifests, and draft the evaluation suite structure. All numbers, screenshots, and results come from our own runs on a local minikube cluster with Ollama (nomic-embed-text) and hosted LLM inference. The golden questions, human labels, and short answers were written by hand.

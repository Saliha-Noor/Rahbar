# RAGOps layer (Assignment 3): commands for every part, A to F

Run from the repository root with the cluster up (`make cluster images apply`, Ollama running on the host).
The code is described in the table at the end; the report skeleton is `docs/RAGOPS-REPORT.md`.
Namespace: `rahbar` (`export NS=rahbar`). Helper: `scripts/ragops.sh` (run it with no argument for its commands).

```bash
make images                                   # also builds rahbar-eval
kubectl apply -k k8s/overlays/dev             # adds PVC ragops-data and ConfigMap rahbar-gate
kubectl apply -f k8s/tools/corpus-loader.yaml # then load the real corpus as in the README, then:
scripts/ragops.sh ingest                      # verify + incremental update, as a Job
```

## Part A  Data management

| item | command |
|---|---|
| A1 verification report (Batch A) | `scripts/ragops.sh ingest` prints one `verified` line per document (4 checks, reason each); the JSON report is `/corpus/_reports/verification-*.json` on the corpus PVC |
| Dry run, nothing moved | `scripts/ragops.sh admin --dry-run` |
| A2 second run, **0 chunks embedded** | `scripts/ragops.sh ingest` again; the log line `ingestion summary` shows `chunks_embedded=0 docs_unchanged=N` |
| Batch B | `scripts/ragops.sh load-batch-b && scripts/ragops.sh ingest`; the log shows each verdict and `quarantined=6 docs_archived=1` |
| Orphans / count by document id | `--audit` and `--count <file>` (below) |
| Archive, rollback | `--archive <file>`, `--restore <file>` (below) |

Admin commands run in the indexer image as a one-off Job built from the CronJob:

```bash
scripts/ragops.sh admin --audit                  # chunks per doc id vs manifest, exit 1 on orphans
scripts/ragops.sh admin --count fees-2026.md     # chunks in the store for one document id
scripts/ragops.sh admin --archive <file>         # flag out of retrieval + move to /corpus/_archive
scripts/ragops.sh admin --restore <file>         # rollback: old version active, newer one archived
scripts/ragops.sh admin --dry-run                # verification report only, nothing moved or indexed
```

Delete proof: remove a file from the PVC (`kubectl exec` into a loader pod), run the Job, then `--count <file>` prints `chunks_in_store: 0` and `--audit` prints `"orphans": {}`.

## Part B  Offline tests

```bash
python eval/check_golden.py                  # does golden.jsonl meet the Part B rules? (lists what is still TODO)
python eval/fill_pages.py --chroma localhost:8000   # after: kubectl port-forward svc/chroma 8000:8000 -n rahbar
python eval/suite.py --api http://localhost:8080 --label baseline --stage A --traces ./traces \
       --label-sheet 10                      # ONE command: all three levels, 2 runs, noise test, result file
scripts/ragops.sh eval baseline api A        # the same suite as a Kubernetes Job (what the demo runs)
```

The result file is `eval/results/<UTC>_<label>.json` (+ `.md` summary table). Label 8+ answers by hand from `label_sheet.md`
into `eval/human_labels.jsonl` (`{"id": "q01", "supported": true}`), re-run, and the judge agreement is reported.

## Part C  Change experiment and gate

```bash
scripts/ragops.sh ingest-collection rahbar-cand 250 25     # candidate: chunk size 250 in its own collection
kubectl apply -f k8s/candidate/api-candidate.yaml          # second Deployment + Service, collection rahbar-cand
scripts/ragops.sh eval candidate api-candidate A           # suite + gate; the Job FAILS if the gate fails
scripts/ragops.sh ingest-collection rahbar-bad 40 5        # deliberately bad: tiny chunks
# point api-candidate at it (kubectl set env deploy/api-candidate CHROMA_COLLECTION=rahbar-bad), then:
scripts/ragops.sh eval bad api-candidate A                 # gate FAILS: screenshot it
python eval/gate.py --candidate eval/results/candidate-latest.json --baseline eval/results/baseline-latest.json
```

## Part D  Traces

```bash
kubectl logs deploy/api -n rahbar | grep '"event": "trace"' | tail -1      # one full record (D1)
kubectl exec deploy/api -n rahbar -- python -m app.tools.trace_show <trace_id>    # D2
kubectl exec deploy/api -n rahbar -- python -m app.tools.trace_summary --since 1h # D3 (also /metrics)
```

D4: ask "What time must students be seated before an exam?" after Batch B: the trace's `guardrails` shows
`redacted_injection` for `exam-conduct-circular.md`. D5: pick a wrong answer from the suite result
(`per_question`, field `request_id`), run `trace_show`, write 5 lines.

## Part E  Coverage and drift

```bash
python eval/coverage.py --stage A  --label before --threshold 0.70   # E2: share covered + uncovered topics
python eval/coverage.py --stage E4 --label after  --threshold 0.70   # E4: coverage rises (exit 1 if < 85%)
scripts/ragops.sh load-batch-b && scripts/ragops.sh ingest           # E3
scripts/ragops.sh eval after-batch-b api B                           # re-run the suite, compare to baseline
scripts/ragops.sh eval after-e4 api E4
```

## Part F  Kubernetes

| item | where |
|---|---|
| F1 | `k8s/base/api.yaml` (Deployment+Service), `chroma.yaml` (StatefulSet), `corpus-pvc.yaml` (data lake, `_quarantine`, `_archive`, `_state`), `ragops-pvc.yaml` |
| F2 | `indexer-job.yaml`, `reindex-cronjob.yaml` (the only code that calls add/update/delete on the store; the API image has no write path), `k8s/eval-job.yaml`, `gate-configmap.yaml`, `k8s/gate-job.yaml` |
| F3 | `k8s/candidate/api-candidate.yaml`; `scripts/ragops.sh release <collection>`, `undo` |
| F4 | traces: stdout + `/data/traces`; `kubectl port-forward deploy/api 8000:8000 -n rahbar` then `curl localhost:8000/metrics` |
| F5 | `scripts/ragops.sh measure` while the suite runs; copy the numbers into the manifests and the report |

Threshold demo (F2): `kubectl edit configmap rahbar-gate -n rahbar` (e.g. `faithfulness_min: 0.99`), then
`kubectl delete job gate -n rahbar --ignore-not-found; kubectl apply -f k8s/gate-job.yaml` with `LABEL` = your candidate:
the Job turns Failed with no rebuild.

Release and rollback (F3):

```bash
scripts/ragops.sh release rahbar-cand        # gate passed: rolling update, maxUnavailable 0, watched by rollout status
scripts/ragops.sh trace-after "What is the CGPA for academic warning?"    # trace shows collection rahbar-cand
scripts/ragops.sh release rahbar-bad         # a bad release
scripts/ragops.sh undo                       # kubectl rollout undo
scripts/ragops.sh trace-after "What is the CGPA for academic warning?"    # trace shows the previous collection + embedding version
```

## Where the code is

| need | file |
|---|---|
| verification (4 checks, quarantine, report) | `indexer/pipeline/verify.py`, `run.py` |
| incremental update, archive, restore, audit | `indexer/pipeline/update.py`, `state.py` |
| Batch B generator | `scripts/make_batch_b.py` |
| trace record, tools, metrics | `api/app/services/trace.py`, `api/app/tools/`, `api/app/metrics_rag.py` |
| retrieval rail (injection) | `api/app/services/guard.py` |
| suite, gate, coverage | `eval/suite.py`, `gate.py`, `coverage.py` |
| tests | `indexer/tests/test_ragops.py`, `api/tests/test_ragops_trace.py` |

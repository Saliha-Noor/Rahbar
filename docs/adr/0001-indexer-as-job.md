# ADR 0001: Run indexing as a Kubernetes Job, not in API startup

## Status
Accepted

## Context
RAHBAR has three API replicas and one persistent Chroma collection. Indexing extracts source documents, cleans and chunks text, calls the embedding model, and writes vectors and metadata. That is a batch operation; it is not part of answering an individual question. The API must be able to restart or roll without unexpectedly rebuilding the collection.

## Decision
The `indexer` runs as a one-shot Kubernetes Job (`k8s/base/indexer-job.yaml`). A weekly CronJob uses the same image and arguments (`k8s/base/reindex-cronjob.yaml`). The API deployment has three replicas (`k8s/base/api.yaml:6`) and only reads the collection. The indexer Job mounts the corpus PVC read-only and writes to Chroma through its service. The API readiness endpoint verifies that the collection exists, is non-empty, and has the expected embedding pin before the pod receives traffic.

## Why indexing must not run in API startup

1. **Concurrent writers corrupt the logical build.** If all three API replicas index during startup, they can race while writing to the same Chroma collection and persistent volume. A partially interleaved index can contain inconsistent or duplicate content. The single indexer Job provides one controlled writer.
2. **Every restart repeats expensive work.** A pod restart, OOM kill, node drain, or rolling update would trigger extraction and embedding again. That increases startup time and load, and couples routine API availability to a batch pipeline. Keeping indexing in a Job means API restarts do not re-index.
3. **Readiness becomes misleading.** If an API reports ready before indexing finishes, it can accept questions against an empty collection. If readiness waits for indexing in startup, new replicas can remain unavailable for minutes and a rollout can replace healthy replicas with replicas still processing documents. The Job completes independently; `/readyz` then gates API traffic on a usable collection.
4. **Re-indexing becomes tied to redeployment.** With indexing in startup, changing corpus material or rebuilding the index requires restarting API pods. With a Job, the operator can create a new Job from the CronJob template while the API deployment remains in place. The assignment's manual command is `kubectl create job --from=cronjob/reindex manual-reindex-1 -n rahbar`.

## Consequences
- API rollout and restart do not trigger indexing.
- Indexing has an explicit lifecycle, retry policy (`backoffLimit: 4`), and resource budget.
- Re-indexing can be initiated independently; the operator must monitor the Job and ensure the collection remains usable during the write.
- The API is deliberately read-only with respect to Chroma.

## Evidence in this repository
- `k8s/base/indexer-job.yaml:1-43` — one-shot Job, `OnFailure`, backoff, and corpus mount.
- `k8s/base/reindex-cronjob.yaml` — scheduled re-index Job template.
- `k8s/base/api.yaml:6` — three API replicas.
- `k8s/base/chroma.yaml:58-65` — Chroma PVC template.
- `api/app/routes/health.py:19-49` — collection, pin, and Redis readiness checks.

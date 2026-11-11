# Engineering notes

Answers below refer to this repository's manifests and code. Where the uploaded evidence does not contain a measurement, that limitation is stated rather than replaced with a guessed number.

## 1. Indexing in API startup: what breaks with 3 replicas and one Chroma volume?

Putting indexing in API startup creates three simultaneous writers against one Chroma collection and PVC. They can interleave document writes and leave an incomplete or inconsistent index. It also repeats expensive extraction and embedding on every API restart, makes readiness ambiguous while indexing is in progress, and ties corpus refreshes to API redeployments. The protection is the dedicated Job in `k8s/base/indexer-job.yaml:1-43`, with `restartPolicy: OnFailure` and a backoff limit. The API deployment is three replicas at `k8s/base/api.yaml:6`; Chroma's persistent volume is declared by `volumeClaimTemplates` at `k8s/base/chroma.yaml:58-65`. Only the Job writes; the API reads.

## 2. Readiness and liveness swapped while Chroma is slow for 90 seconds

The current API liveness endpoint `/healthz` is deliberately dependency-free (`api/app/routes/health.py:13-16`), while readiness `/readyz` checks Chroma, collection count, embedding pin, and Redis (`api/app/routes/health.py:19-49`). The Deployment wires liveness to `/healthz` and readiness to `/readyz` (`k8s/base/api.yaml:48-56`). If swapped, each API pod's liveness check would fail when Chroma is slow, and kubelet would restart otherwise healthy API processes. Across three replicas this can create a restart storm: all pods lose their local process state while the shared dependency remains slow, reducing availability rather than allowing Kubernetes to keep the processes alive but temporarily remove them from Service endpoints. With the current arrangement, readiness failure removes a pod from traffic without restarting it.

## 3. What does the CPU-based HPA measure during generation, and what should scale it?

The HPA measures CPU utilisation as observed CPU usage divided by the pod's CPU request; it does not measure time spent waiting for Ollama or the number of requests waiting for generation. The supplied `top-pods.txt` shows API pods around 7–8m CPU against the 100m request in `k8s/base/api.yaml:40-42`, approximately 7–8% utilisation. The supplied HPA snapshot in `docs/evidence/hpa.txt` is 7%/70%, with min 3, max 8, and currently 3 replicas. The separate eight-pod snapshot does not prove what caused scale-out; the user recalls a load test, but the trigger was not captured.

A generation service should scale on a queueing/concurrency signal such as pending requests, in-flight generations, or request wait time (and possibly tokens/second), not CPU alone. To use that signal, instrument and expose it as a Prometheus metric, deploy a metrics adapter such as Prometheus Adapter or KEDA, and configure an HPA with an external or custom metric. CPU HPA remains a useful safety signal but is not a proxy for LLM demand.

## 4. Indexer peak memory, limit, margin, and exit code

The Job requests 256Mi and has a 1Gi memory limit (`k8s/base/indexer-job.yaml:31-33`). If a container exceeds its memory limit, Kubernetes reports `OOMKilled`; the process commonly exits with code 137 (SIGKILL). The uploaded `docs/evidence/top-indexer.txt` is zero bytes, and the supplied monitoring loop returned no matching lines. Therefore the real peak and remaining margin cannot be calculated from the available evidence. Do not claim that the 1Gi limit has a measured safety margin until a `kubectl top pods` sample is captured while the indexer is running. The current evidence does not establish whether the manual re-index Job was OOMKilled.

## 5. Where should recall@5 be weakest, and why?

The golden set separates ordinary, version-sensitive, exact-term, abstention, and injection questions (`eval/golden.yaml`). Exact-term retrieval is the most likely weak category: dense embeddings represent semantic similarity, so short identifiers such as clause numbers, course codes, and numeric thresholds can be blurred by surrounding language. The implementation addresses this with a literal exact-term lookup (`where_document: $contains`) and merges those matches with vector results (`api/app/retrieval/chroma.py`). The actual weakest category and its recall@5 value must be taken from `eval/results.json`; that file was absent from the uploaded repository, so no numerical ranking is claimed here.

## 6. EMBED_MODEL changed only on the API

The API compares the collection's stored `embed_model` metadata with its own ConfigMap setting. On mismatch, `/readyz` returns HTTP 503 with `failed: embedding-pin` and identifies the index and API model names (`api/app/routes/health.py:39-44`). The pod remains Running but is not Ready and is excluded from the Service. `docs/evidence/pin-mismatch.txt` records this exact behavior: the index was built with `dummy-768` while the API expected `nomic-embed-text`. Without this guardrail, query vectors from a different embedding space would be compared with stored vectors, returning meaningless retrieval results without an obvious error.

## 7. A debugging failure

The committed failure evidence shows an API pod held at 0/1 Ready because the embedding pin did not match: the index metadata said `dummy-768`, while the API ConfigMap expected `nomic-embed-text`. The initial temptation in this situation is to treat a Running-but-not-Ready pod as a generic startup or Chroma availability issue. The decisive evidence was the readiness response and log field `failed: embedding-pin`, followed by the explicit reason in `docs/evidence/pin-mismatch.txt`. The correct remedy is to rebuild the index with the same `EMBED_MODEL` used by the API (or deliberately align the ConfigMap and rebuild), not to weaken the readiness probe. The evidence proves the failure and diagnosis; it does not record how many minutes it consumed, so the team should add the verified duration and the person's account if this is the incident selected for the assignment's “more than an hour” prompt.

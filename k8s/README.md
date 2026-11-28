# Kubernetes manifests (RAGOps additions)

`k8s/base/` and `k8s/overlays/` are the Assignment 02 deployment (kustomize). The RAGOps layer adds:

| file | what |
|---|---|
| `base/ragops-pvc.yaml` | PVC `ragops-data`: traces (`/data/traces`) and evaluation results (`/data/results`) |
| `base/gate-configmap.yaml` | ConfigMap `rahbar-gate`: release-gate thresholds (`gate.yaml`) |
| `base/api.yaml`, `configmap.yaml` | API mounts `/data`; `TRACE_DIR`, `LLM_SEED`, `EMBED_VERSION` |
| `base/indexer-job.yaml`, `reindex-cronjob.yaml` | corpus PVC mounted read-write: `_quarantine`, `_archive`, `_state`, `_reports` |
| `base/networkpolicy.yaml` | extra policies for the candidate API and the evaluation Job |
| `eval-job.yaml` | the suite + gate as a Job (`kubectl apply -f k8s/eval-job.yaml`) |
| `gate-job.yaml` | the gate only, for the ConfigMap-threshold demo |
| `candidate/api-candidate.yaml` | candidate Deployment + Service with its own collection |

Fresh cluster, in order:

```bash
make cluster                        # minikube + Calico + metrics-server + ingress
make images                         # api, indexer, ui, eval images, loaded into minikube
kubectl apply -k k8s/overlays/dev   # base + RAGOps additions
# load the corpus and run the indexer exactly as in the main README, then:
kubectl apply -f k8s/eval-job.yaml  # baseline suite (LABEL=baseline)
kubectl apply -f k8s/candidate/api-candidate.yaml
```

Resources (F5): requests and limits in these files are starting values. Replace them with your
`kubectl top pods -n rahbar` readings taken during an ingestion Job and an evaluation Job, and copy the
numbers into the report. The evaluation image is `rahbar-eval:dev`; rebuild it after editing `eval/golden.jsonl`.

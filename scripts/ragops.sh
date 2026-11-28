#!/usr/bin/env bash
# RAGOps helper for the Kubernetes demo. Run from the repository root.
#   scripts/ragops.sh load-batch-b            copy corpus/batch_b into the corpus PVC
#   scripts/ragops.sh ingest [name]           run the ingestion Job (verify + incremental update)
#   scripts/ragops.sh admin ARGS...           run `python -m pipeline.run ARGS` as a Job (--audit, --count F, --archive F, --restore F, --dry-run)
#   scripts/ragops.sh ingest-collection NAME CHUNK_SIZE [OVERLAP]   build a candidate collection
#   scripts/ragops.sh eval LABEL [SERVICE] [STAGE]   run the suite + gate Job against a Service
#   scripts/ragops.sh release COLLECTION      rolling update of the live API to a collection
#   scripts/ragops.sh undo                    kubectl rollout undo of the live API
#   scripts/ragops.sh trace-after "question"  ask the live API and print the trace
#   scripts/ragops.sh pull                    copy traces and results from the cluster into the repo
#   scripts/ragops.sh measure                 kubectl top, for the F5 resource numbers
set -euo pipefail
NS="${NS:-rahbar}"
cmd="${1:-help}"; shift || true

wait_job() { kubectl wait --for=condition=complete "job/$1" -n "$NS" --timeout="${2:-900s}" 2>&1 || \
             kubectl wait --for=condition=failed "job/$1" -n "$NS" --timeout=5s 2>&1 || true; }

case "$cmd" in
  load-batch-b)
    python3 scripts/make_batch_b.py
    kubectl apply -f k8s/tools/corpus-loader.yaml
    kubectl wait --for=condition=Ready pod/corpus-loader -n "$NS" --timeout=120s
    for f in corpus/batch_b/*; do [ "$(basename "$f")" = README.md ] || kubectl cp "$f" "$NS/corpus-loader:/corpus/$(basename "$f")"; done
    kubectl delete pod corpus-loader -n "$NS" --wait=false
    echo "Batch B copied. Now: scripts/ragops.sh ingest" ;;
  ingest)
    name="${1:-ingest-$(date +%s)}"
    kubectl create job "$name" --from=cronjob/reindex -n "$NS"
    wait_job "$name"; kubectl logs -n "$NS" "job/$name" ;;
  admin)
    name="admin-$(date +%s)"
    kubectl create job "$name" --from=cronjob/reindex -n "$NS" --dry-run=client -o json \
      | ARGS_JSON="$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1:]))' "$@")" python3 -c "
import json,sys,os
j=json.load(sys.stdin); c=j['spec']['template']['spec']['containers'][0]
c['args']=['python','-m','pipeline.run']+json.loads(os.environ['ARGS_JSON'])
print(json.dumps(j))" | kubectl apply -f -
    wait_job "$name" 300s; kubectl logs -n "$NS" "job/$name" | grep -v '"indexer starting"' ;;
  ingest-collection)
    coll="$1"; size="$2"; ovl="${3:-50}"; name="ingest-$coll-$(date +%s)"
    kubectl create job "$name" --from=cronjob/reindex -n "$NS" --dry-run=client -o json \
      | python3 -c "
import json,sys
j=json.load(sys.stdin); c=j['spec']['template']['spec']['containers'][0]
c['env']=[{'name':'CHROMA_COLLECTION','value':'$coll'},{'name':'CHUNK_SIZE','value':'$size'},{'name':'CHUNK_OVERLAP','value':'$ovl'}]
c['args']=['python','-m','pipeline.run','--rebuild']
print(json.dumps(j))" | kubectl apply -f -
    wait_job "$name"; kubectl logs -n "$NS" "job/$name" | tail -5 ;;
  eval)
    label="$1"; svc="${2:-api}"; stage="${3:-A}"
    kubectl delete job eval -n "$NS" --ignore-not-found
    sed -e "s#value: baseline }#value: $label }#" -e "s#http://api:8000#http://$svc:8000#" \
        -e "s#{ name: STAGE, value: A }#{ name: STAGE, value: $stage }#" k8s/eval-job.yaml | kubectl apply -f -
    wait_job eval 3000s; kubectl logs -n "$NS" job/eval | tail -30
    kubectl get job eval -n "$NS" ;;
  release)
    kubectl set env deployment/api -n "$NS" CHROMA_COLLECTION="$1"
    kubectl rollout status deployment/api -n "$NS" --timeout=300s ;;
  undo)
    kubectl rollout undo deployment/api -n "$NS"
    kubectl rollout status deployment/api -n "$NS" --timeout=300s ;;
  trace-after)
    q="${1:?question}"
    rid=$(kubectl exec -n "$NS" deploy/api -- python -c "
import httpx,sys,json
r=httpx.post('http://localhost:8000/api/ask',json={'question':sys.argv[1]},headers={'X-Cache-Bypass':'1'},timeout=300)
print(r.json()['request_id'])" "$q")
    kubectl exec -n "$NS" deploy/api -- python -m app.tools.trace_show "$rid" ;;
  pull)
    mkdir -p eval/results traces
    kubectl exec -n "$NS" deploy/api -- tar -C /data/results -cf - . | tar -C eval/results -xf -
    kubectl exec -n "$NS" deploy/api -- tar -C /data/traces -cf - . | tar -C traces -xf -
    echo "copied to eval/results/ and traces/ : commit them" ;;
  measure)
    kubectl top pods -n "$NS"; kubectl top nodes ;;
  *) sed -n 2,16p "$0" ;;
esac

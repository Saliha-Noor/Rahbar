#!/bin/sh
# Entry point of the evaluation Job (k8s/eval-job.yaml). Runs the suite, then the release gate.
# The Job exits non-zero when the gate fails, so `kubectl get job` shows Failed for a bad candidate.
#   LABEL=baseline          run the suite only (it becomes the baseline)
#   LABEL=<anything else>   run the suite, then gate it against $RESULTS_DIR/baseline-latest.json
#   GATE_ONLY=1             re-apply the gate to the last result of LABEL (threshold-change demo)
set -eu
R="${RESULTS_DIR:-/data/results}"
if [ "${GATE_ONLY:-0}" != "1" ]; then
  python suite.py --label "$LABEL" --out-dir "$R" ${SUITE_ARGS:-}
fi
if [ "$LABEL" = "baseline" ]; then echo "baseline recorded, no gate"; exit 0; fi
python gate.py --candidate "$R/$LABEL-latest.json" --baseline "$R/baseline-latest.json"

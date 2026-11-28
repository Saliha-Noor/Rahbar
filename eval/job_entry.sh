#!/bin/sh

set -eu
R="${RESULTS_DIR:-/data/results}"
if [ "${GATE_ONLY:-0}" != "1" ]; then
  python suite.py --label "$LABEL" --out-dir "$R" ${SUITE_ARGS:-}
fi
if [ "$LABEL" = "baseline" ]; then echo "baseline recorded, no gate"; exit 0; fi
python gate.py --candidate "$R/$LABEL-latest.json" --baseline "$R/baseline-latest.json"

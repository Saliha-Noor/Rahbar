#!/usr/bin/env python3
"""Release gate (assignment C2). Exit 0 = pass, 1 = fail.

    python eval/gate.py --candidate eval/results/cand-latest.json --baseline eval/results/baseline-latest.json
    GATE_CONFIG=/config/gate.yaml python eval/gate.py ...     # the cluster: thresholds from a ConfigMap
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent


def evaluate(cand: dict, base: dict, cfg: dict) -> list[dict]:
    c, e = cand["component"], cand["end_to_end"]
    be, bc = base["end_to_end"], base["component"]
    checks = []

    def add(name: str, ok: bool | None, detail: str) -> None:
        checks.append({"check": name, "result": "skip" if ok is None else ("pass" if ok else "FAIL"),
                       "detail": detail})

    drop = cfg.get("recall_at_5_max_drop_points")
    if drop is not None and c["recall@5"] is not None and bc["recall@5"] is not None:
        d = (bc["recall@5"] - c["recall@5"]) * 100
        add("recall@5 drop", d <= drop, f"candidate {c['recall@5']} vs baseline {bc['recall@5']}: "
                                        f"drop {d:.1f} points, allowed {drop}")
    fm = cfg.get("faithfulness_min")
    if fm is not None:
        v = e.get("faithfulness")
        add("faithfulness", v is not None and v >= fm,
            f"{v} (minimum {fm})" if v is not None else "NOT MEASURED (judge or traces unavailable)")
    p95 = cfg.get("p95_latency_max_s")
    if p95 is not None:
        add("p95 latency", e["latency_p95_s"] <= p95, f"{e['latency_p95_s']} s (maximum {p95})")
    if cfg.get("abstention_not_below_baseline") and e["abstention_correctness"] is not None:
        add("abstention", e["abstention_correctness"] >= (be["abstention_correctness"] or 0),
            f"{e['abstention_correctness']} vs baseline {be['abstention_correctness']}")
    cv = cfg.get("citation_validity_min")
    if cv is not None and e["citation_validity"] is not None:
        add("citation validity", e["citation_validity"] >= cv, f"{e['citation_validity']} (minimum {cv})")
    return checks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--config", default=os.environ.get("GATE_CONFIG", str(HERE / "gate.yaml")))
    a = ap.parse_args()
    cfg = yaml.safe_load(Path(a.config).read_text()) or {}
    cand, base = json.loads(Path(a.candidate).read_text()), json.loads(Path(a.baseline).read_text())
    checks = evaluate(cand, base, cfg)
    print(f"gate config: {a.config}\ncandidate: {cand['label']} ({(cand.get('index') or {}).get('collection')})"
          f"   baseline: {base['label']} ({(base.get('index') or {}).get('collection')})\n")
    for k in checks:
        print(f"  [{k['result']:>4}] {k['check']:<18} {k['detail']}")
    failed = [k for k in checks if k["result"] == "FAIL"]
    print("\nGATE FAILED: " + ", ".join(k["check"] for k in failed) if failed else "\nGATE PASSED")
    out = Path(a.candidate).with_name(f"{cand['label']}-gate.json")
    out.write_text(json.dumps({"passed": not failed, "config": cfg, "checks": checks}, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

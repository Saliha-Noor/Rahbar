#!/usr/bin/env python3
"""D3: summarise the trace log over a time window.

    python -m app.tools.trace_summary --since 1h
    python -m app.tools.trace_summary --since 2026-11-23T10:00:00 --until 2026-11-23T12:00:00 --json
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone


def pct(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 1)


def parse_when(s: str) -> datetime:
    m = re.fullmatch(r"(\d+)([smhd])", s)
    if m:
        unit = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}[m.group(2)]
        return datetime.now(timezone.utc) - timedelta(**{unit: int(m.group(1))})
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def load(directory: str, since: datetime, until: datetime) -> list[dict]:
    out = []
    for path in sorted(glob.glob(os.path.join(directory, "*.jsonl"))):
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    t = datetime.fromisoformat(r["ts"])
                except (ValueError, KeyError):
                    continue
                if since <= t <= until:
                    out.append(r)
    return out


def summarise(recs: list[dict]) -> dict:
    n = len(recs)
    top1 = [r["retrieved"][0]["score"] for r in recs if r.get("retrieved")]
    stages: dict[str, list[float]] = {}
    for r in recs:
        for k, v in r["latency_ms"].items():
            stages.setdefault(k, []).append(v)
    hist = {f"{lo:.1f}-{lo + 0.1:.1f}": sum(lo <= x < lo + 0.1 + (1e-9 if lo >= 0.9 else 0) for x in top1)
            for lo in [i / 10 for i in range(2, 10)]}
    return {
        "queries": n,
        "window": [min((r["ts"] for r in recs), default=None), max((r["ts"] for r in recs), default=None)],
        "abstention_rate": round(sum(not r["answered_from_context"] for r in recs) / n, 3) if n else None,
        "outcomes": {o: sum(r["outcome"] == o for r in recs) for o in sorted({r["outcome"] for r in recs})},
        "cache_hit_rate": round(sum(r["cache"] == "hit" for r in recs) / n, 3) if n else None,
        "top1_similarity": {"p10": pct(top1, 10), "p50": pct(top1, 50), "p90": pct(top1, 90),
                            "histogram": hist},
        "latency_ms_p95_per_stage": {k: pct(v, 95) for k, v in sorted(stages.items())},
        "latency_ms_p50_per_stage": {k: pct(v, 50) for k, v in sorted(stages.items())},
        "injection_flags": sum(len(r["guardrails"]) for r in recs),
        "injection_by_action": {a: sum(g["action"] == a for r in recs for g in r["guardrails"])
                                for a in sorted({g["action"] for r in recs for g in r["guardrails"]})},
        "collections": sorted({f"{r['collection']['name']}@{r['embedding']['version']}" for r in recs}),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.environ.get("TRACE_DIR", "/data/traces"))
    ap.add_argument("--since", default="24h")
    ap.add_argument("--until", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    until = parse_when(a.until) if a.until else datetime.now(timezone.utc) + timedelta(minutes=1)
    s = summarise(load(a.dir, parse_when(a.since), until))
    print(json.dumps(s, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

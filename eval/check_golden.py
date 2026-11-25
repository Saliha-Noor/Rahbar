#!/usr/bin/env python3
"""Check eval/golden.jsonl against the assignment's Part B requirements. Exit 1 if any fails."""

from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "golden.jsonl"
rows = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
base = [r for r in rows if r.get("since", "A") == "A"]   # what exists when the Part B suite first runs
checks = {
    ">= 25 questions at baseline stage": len(base) >= 25,
    ">= 15 answerable": sum(r["kind"] == "answerable" for r in base) >= 15,
    ">= 5 unanswerable": sum(r["kind"] == "unanswerable" for r in base) >= 5,
    ">= 5 hard": sum(bool(r["hard"]) for r in base) >= 5,
    ">= 8 human-written": sum(r["origin"] == "human" for r in base) >= 8,
    ">= 8 synthetic reviewed by hand": sum(r["origin"] == "synthetic" and r["reviewed"] for r in base) >= 8,
    "every row labelled human|synthetic": all(r["origin"] in ("human", "synthetic") for r in rows),
    "answerable rows have ground-truth source and page":
        all(r["relevant"] and all(x["source"] and x.get("page") is not None for x in r["relevant"])
            for r in rows if r["kind"] == "answerable"),
    ">= 6 questions added in E4": sum(r.get("since") == "E4" for r in rows) >= 6,
}
for k, v in checks.items():
    print(f"[{'ok' if v else 'TODO':>4}] {k}")
print(f"\n{len(rows)} questions: {len(base)} baseline, {sum(r.get('since') == 'B' for r in rows)} for Batch B, "
      f"{sum(r.get('since') == 'E4' for r in rows)} added in E4; unreviewed synthetic: "
      f"{sum(r['origin'] == 'synthetic' and not r['reviewed'] for r in rows)}")
sys.exit(0 if all(checks.values()) else 1)

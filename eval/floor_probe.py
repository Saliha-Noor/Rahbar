#!/usr/bin/env python3
"""Print the top retrieval score of every golden question, to choose RELEVANCE_FLOOR.

    python eval/floor_probe.py --api http://localhost:8001 [--golden eval/golden.yaml]

Pick a floor between the highest score of a must-abstain question and the lowest score
of an answerable one. Put both ranges in docs/PIPELINE.md.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import httpx
import yaml

HERE = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8001")
    ap.add_argument("--golden", type=Path, default=HERE / "golden.yaml")
    args = ap.parse_args()
    qs = yaml.safe_load(args.golden.read_text(encoding="utf-8"))["questions"]
    answer, abstain = [], []
    for q in qs:
        r = httpx.post(f"{args.api}/api/ask", json={"question": q["question"]}, timeout=120).json()
        top = r["retrieved"][0]["score"] if r["retrieved"] else 0.0
        kind = "ABSTAIN" if q.get("must_abstain") else "answer"
        (abstain if q.get("must_abstain") else answer).append(top)
        print(f'{q["id"]:<5} {kind:<8} top_score={top:.3f}')
    if answer and abstain:
        print(f"\nanswerable: min {min(answer):.3f}   must-abstain: max {max(abstain):.3f}")
        print("choose RELEVANCE_FLOOR between those two numbers")


if __name__ == "__main__":
    main()

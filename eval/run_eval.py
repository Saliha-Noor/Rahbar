#!/usr/bin/env python3
"""Score a running RAHBAR against a golden set, and gate CI on the result (section 5).

    python eval/run_eval.py --api http://<ingress>                 # your corpus
    python eval/run_eval.py --api ... --golden eval/fixtures/golden.fixture.yaml
    python eval/run_eval.py --api ... --update-baseline            # after a deliberate improvement

Exit code 0 when every gate passes, 1 when any fails. CI relies on that exit code.

Given: talking to the API, reading the golden set, writing results.json, the exit
code. The four scoring functions (recall_at_k, citation_validity, summarise, gate) are the evaluation.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx
import yaml

HERE = Path(__file__).resolve().parent

# The gate from section 5.4. Change these only with a reason written in docs/PIPELINE.md.
MAX_RECALL5_DROP = 0.05        # recall@5 may fall at most 5 points below the baseline
MIN_CITATION_VALIDITY = 0.95   # at least 95% of citations must match retrieved passages
REQUIRED_ABSTENTION = 1.0      # every must-abstain question must be declined


def load_golden(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    questions = data.get("questions") or []
    if not questions:
        sys.exit(f"no questions in {path}")
    return questions


def ask(client: httpx.Client, api: str, question: str) -> dict:
    """POST one question and return the AskResponse as a dict (see api/app/schemas.py)."""
    response = client.post(f"{api.rstrip('/')}/api/ask", json={"question": question})
    response.raise_for_status()
    return response.json()


def _sec(gold: str, got: str) -> bool:
    """Section matching rule (write it in docs/PIPELINE.md): the golden section is a prefix
    of the stored one, case-insensitive, and not followed by another digit. So golden "5.4"
    matches "5.4 Academic Warning" and "5.4.1 ...", but not "5.41"."""
    return re.match(re.escape(gold.lower().strip()) + r"(?!\d)", got.lower().strip()) is not None


def _hit(rel: dict, ret: dict) -> bool:
    return rel["source"].lower() == ret["source"].lower() and _sec(rel["section"], ret["section"])


def recall_at_k(relevant: list[dict], retrieved: list[dict], k: int) -> float | None:
    """Fraction of the relevant (source, section) pairs found in the top k retrieved.
    Return None when the question has no relevant passages (must-abstain questions)."""
    if not relevant:
        return None
    top = retrieved[:k]
    return sum(any(_hit(r, t) for t in top) for r in relevant) / len(relevant)


def citation_validity(response: dict) -> float | None:
    """Fraction of the response's citations that match a passage in response['retrieved'].
    Return None when there are no citations."""
    cites = response.get("citations") or []
    if not cites:
        return None
    ok = sum(
        any(c["source"] == t["source"] and c["section"] == t["section"]
            for t in response["retrieved"])
        for c in cites
    )
    return ok / len(cites)


def _avg(values) -> float | None:  # type: ignore[no-untyped-def]
    xs = [x for x in values if x is not None]
    return round(sum(xs) / len(xs), 4) if xs else None


def summarise(rows: list[dict]) -> dict:
    """Overall recall@3, recall@5, citation validity and abstention correctness, plus
    recall@5 broken down by question type. This dict becomes results.json."""
    by_type: dict[str, list[float | None]] = {}
    for r in rows:
        by_type.setdefault(r["type"], []).append(
            recall_at_k(r["relevant"], r["response"]["retrieved"], 5))
    abstain = [r for r in rows if r["must_abstain"]]
    return {
        "recall@3": _avg(recall_at_k(r["relevant"], r["response"]["retrieved"], 3) for r in rows),
        "recall@5": _avg(recall_at_k(r["relevant"], r["response"]["retrieved"], 5) for r in rows),
        "recall@5_by_type": {t: _avg(v) for t, v in by_type.items()},
        "citation_validity": _avg(citation_validity(r["response"]) for r in rows),
        "abstention_correctness": (
            sum(not r["response"]["answered_from_context"] for r in abstain) / len(abstain)
            if abstain else None),
    }


def gate(results: dict, baseline: dict | None) -> list[str]:
    """Return one message per failed gate (section 5.4); an empty list means pass."""
    failures: list[str] = []
    base = (baseline or {}).get("recall@5")
    if base is not None and results["recall@5"] is not None \
            and results["recall@5"] < base - MAX_RECALL5_DROP:
        failures.append(
            f"recall@5 {results['recall@5']} is more than 5 points below baseline {base}")
    ab = results["abstention_correctness"]
    if ab is not None and ab < REQUIRED_ABSTENTION:
        failures.append(f"a must-abstain question was answered from context (abstention={ab})")
    cv = results["citation_validity"]
    if cv is not None and cv < MIN_CITATION_VALIDITY:
        failures.append(f"citation validity {cv} is below {MIN_CITATION_VALIDITY}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate RAHBAR against a golden set.")
    parser.add_argument("--api", required=True, help="base URL, e.g. http://192.168.49.2")
    parser.add_argument("--host", help="Host header, when your Ingress rule names a host")
    parser.add_argument("--golden", type=Path, default=HERE / "golden.yaml")
    parser.add_argument("--baseline", type=Path, default=HERE / "baseline.json")
    parser.add_argument("--out", type=Path, default=HERE / "results.json")
    parser.add_argument("--update-baseline", action="store_true",
                        help="write these results as the new baseline")
    args = parser.parse_args()

    questions = load_golden(args.golden)
    rows = []
    headers = {"Host": args.host} if args.host else {}
    with httpx.Client(timeout=120.0, headers=headers) as client:
        for q in questions:
            started = time.perf_counter()
            response = ask(client, args.api, q["question"])
            rows.append({
                "id": q["id"], "type": q.get("type", "ordinary"),
                "must_abstain": bool(q.get("must_abstain", False)),
                "relevant": q.get("relevant") or [],
                "expect": q.get("expect"),
                "response": response,
                "seconds": round(time.perf_counter() - started, 2),
            })
            print(f"  {q['id']:<5} {rows[-1]['seconds']:>6.2f}s  {q['question'][:60]}")

    try:
        results = summarise(rows)
        baseline = json.loads(args.baseline.read_text()) if args.baseline.exists() else None
        failures = gate(results, baseline)
    except NotImplementedError as exc:
        print(f"\nnot implemented yet: {exc}")
        return 2

    results["golden"] = str(args.golden)
    results["questions"] = len(rows)
    args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nresults written to {args.out}")
    if args.update_baseline:
        args.baseline.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"baseline updated: {args.baseline}")

    if failures:
        print("\nGATE FAILED")
        for message in failures:
            print(f"  - {message}")
        return 1
    print("\ngate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

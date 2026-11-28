#!/usr/bin/env python3
"""Query coverage (assignment E2/E4): do the golden questions still match what users ask?

For each live query, find the most similar golden question (cosine of embeddings). A query is
COVERED when that similarity is at least --threshold. The paper flags a gap when fewer than
85 percent of live queries reach the threshold. Exit code 1 when coverage is below --min-coverage.

    python eval/coverage.py --stage A  --label before
    python eval/coverage.py --stage E4 --label after
    python eval/coverage.py --backend hash        # offline check, no Ollama (CI only)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
STAGES = {"A": 0, "B": 1, "E4": 2}
STOP = set("the a an of to in is are what how do does can i my for and or on at by it this that with "
           "from be there any which who when where".split())


def cos(a: list[float], b: list[float]) -> float:
    n = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b)) / n if n else 0.0


def hash_embed(t: str, dim: int = 256) -> list[float]:
    v = [0.0] * dim
    for w in re.findall(r"[a-z0-9]+", t.lower()):
        h = int.from_bytes(hashlib.md5(w.encode()).digest()[:4], "big")
        v[h % dim] += 1.0 if (h >> 31) & 1 else -1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def embed_all(texts: list[str], a: argparse.Namespace) -> list[list[float]]:
    if a.backend == "hash":
        return [hash_embed(t) for t in texts]
    out: list[list[float]] = []
    for i in range(0, len(texts), 32):
        r = httpx.post(f"{a.ollama}/api/embed", json={"model": a.embed_model, "input": texts[i : i + 32]}, timeout=300)
        r.raise_for_status()
        out += r.json()["embeddings"]
    return out


def topics(uncovered: list[dict], link: float) -> list[dict]:
    """Greedy grouping of uncovered queries by similarity; label = most common content words."""
    groups: list[list[dict]] = []
    for q in uncovered:
        for g in groups:
            if cos(q["vec"], g[0]["vec"]) >= link:
                g.append(q)
                break
        else:
            groups.append([q])
    out = []
    for g in groups:
        words = Counter(w for q in g for w in re.findall(r"[a-z]{3,}", q["query"].lower()) if w not in STOP)
        out.append({"topic_hint": " ".join(w for w, _ in words.most_common(3)),
                    "queries": [q["query"] for q in g]})
    return sorted(out, key=lambda t: -len(t["queries"]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--queries", default=str(HERE / "live_queries.jsonl"))
    ap.add_argument("--golden", default=str(HERE / "golden.jsonl"))
    ap.add_argument("--stage", default="E4", choices=list(STAGES))
    ap.add_argument("--threshold", type=float, default=float(os.environ.get("COVERAGE_THRESHOLD", 0.70)),
                    help="similarity at which a live query counts as covered (justify it in the report)")
    ap.add_argument("--min-coverage", type=float, default=float(os.environ.get("MIN_COVERAGE", 0.85)))
    ap.add_argument("--link", type=float, default=0.60, help="similarity for grouping uncovered queries")
    ap.add_argument("--backend", choices=["ollama", "hash"], default="ollama")
    ap.add_argument("--ollama", default=os.environ.get("OLLAMA_URL", "http://host.minikube.internal:11434"))
    ap.add_argument("--embed-model", default=os.environ.get("EMBED_MODEL", "nomic-embed-text"))
    ap.add_argument("--label", default="coverage")
    ap.add_argument("--out-dir", default=os.environ.get("RESULTS_DIR", str(HERE / "results")))
    a = ap.parse_args()

    gold = [json.loads(x) for x in Path(a.golden).read_text().splitlines() if x.strip()]
    gold = [g for g in gold if STAGES[g.get("since", "A")] <= STAGES[a.stage]]
    qs = [json.loads(x) for x in Path(a.queries).read_text().splitlines() if x.strip()]
    gv = embed_all([g["question"] for g in gold], a)
    qv = embed_all([q["query"] for q in qs], a)
    rows = []
    for q, v in zip(qs, qv):
        sims = [cos(v, g) for g in gv]
        i = max(range(len(sims)), key=sims.__getitem__)
        rows.append({"query": q["query"], "domain": q.get("domain"), "vec": v, "best_sim": round(sims[i], 3),
                     "nearest_golden": gold[i]["id"], "nearest_question": gold[i]["question"]})
    covered = [r for r in rows if r["best_sim"] >= a.threshold]
    unc = [r for r in rows if r["best_sim"] < a.threshold]
    cov = len(covered) / len(rows)
    sims_sorted = sorted(r["best_sim"] for r in rows)
    result = {"label": a.label, "stage": a.stage, "golden_questions": len(gold), "live_queries": len(rows),
              "threshold": a.threshold, "coverage": round(cov, 3), "min_coverage": a.min_coverage,
              "similarity_quartiles": [sims_sorted[int(len(sims_sorted) * p)] for p in (0.0, 0.25, 0.5, 0.75)],
              "uncovered": [{k: r[k] for k in ("query", "best_sim", "nearest_golden")} for r in unc],
              "topics": topics(unc, a.link)}
    Path(a.out_dir).mkdir(parents=True, exist_ok=True)
    Path(a.out_dir, f"coverage-{a.label}.json").write_text(json.dumps(result, indent=2))
    print(f"golden questions: {len(gold)} (stage {a.stage})   live queries: {len(rows)}   threshold: {a.threshold}")
    print(f"coverage: {len(covered)}/{len(rows)} = {cov:.1%}   (minimum {a.min_coverage:.0%})")
    print("uncovered queries, grouped:")
    for t in result["topics"]:
        print(f"  - {t['topic_hint']}: {len(t['queries'])}")
        for q in t["queries"]:
            print(f"      {q}")
    ok = cov >= a.min_coverage
    print("\nCOVERAGE OK" if ok else "\nCOVERAGE GAP: add golden questions for the topics above")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

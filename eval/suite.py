#!/usr/bin/env python3
"""The RAGOps evaluation suite: three levels in one command (assignment Part B).

    python eval/suite.py --api http://api:8000 --label baseline --traces /data/traces
    python eval/suite.py --api http://192.168.49.2 --host rahbar.local --label candidate-c250

Levels
  module     embedding model: paraphrase vs unrelated cosine, time per chunk, determinism
  component  retrieval: recall@3, recall@5, MRR, nDCG@5, page match; noise test (typos in queries)
  end-to-end faithfulness (LLM judge + human agreement), abstention, citations, latency p50/p95
It runs the question set twice (--runs 2) and reports the difference per metric.
Writes eval/results/<UTC timestamp>_<label>.json and .md and <label>-latest.json.
The API is asked with X-Cache-Bypass: 1, so the numbers do not depend on what is cached.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_eval as RE  # noqa: E402  (reuses the section-matching rule and citation check)

HERE = Path(__file__).resolve().parent
STAGES = {"A": 0, "B": 1, "E4": 2}


# ----------------------------------------------------------------------------- helpers
def load_golden(path: Path, stage: str) -> list[dict]:
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    return [r for r in rows if STAGES[r.get("since", "A")] <= STAGES[stage]]


def cos(a: list[float], b: list[float]) -> float:
    n = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b)) / n if n else 0.0


def pct(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 3)


def mean(xs: list[float | None]) -> float | None:
    v = [x for x in xs if x is not None]
    return round(sum(v) / len(v), 4) if v else None


def typo(text: str, rng: random.Random, rate: float) -> str:
    out = []
    for w in text.split():
        if len(w) > 4 and rng.random() < rate:
            i = rng.randrange(1, len(w) - 2)
            w = w[:i] + w[i + 1] + w[i] + w[i + 2 :]
        out.append(w)
    return " ".join(out)


def embed(ollama: str, model: str, texts: list[str]) -> list[list[float]]:
    r = httpx.post(f"{ollama}/api/embed", json={"model": model, "input": texts}, timeout=300)
    r.raise_for_status()
    return r.json()["embeddings"]


# ----------------------------------------------------------------------------- ranking metrics
def _rel_flags(relevant: list[dict], retrieved: list[dict], k: int) -> list[int]:
    return [int(any(RE._hit(r, t) for r in relevant)) for t in retrieved[:k]]


def mrr(relevant: list[dict], retrieved: list[dict]) -> float | None:
    if not relevant:
        return None
    for i, flag in enumerate(_rel_flags(relevant, retrieved, len(retrieved)), 1):
        if flag:
            return 1.0 / i
    return 0.0


def ndcg_at(relevant: list[dict], retrieved: list[dict], k: int = 5) -> float | None:
    if not relevant:
        return None
    flags = _rel_flags(relevant, retrieved, k)
    dcg = sum(f / math.log2(i + 2) for i, f in enumerate(flags))
    ideal = sum(1 / math.log2(i + 2) for i in range(min(len(relevant), k)))
    return dcg / ideal if ideal else 0.0


def page_match(relevant: list[dict], retrieved: list[dict], k: int = 5) -> float | None:
    gold = [r for r in relevant if r.get("page") is not None]
    if not gold:
        return None
    return sum(any(RE._hit(r, t) and t.get("page") == r["page"] for t in retrieved[:k])
               for r in gold) / len(gold)


# ----------------------------------------------------------------------------- module level
def module_level(args: argparse.Namespace) -> dict:
    pairs = [json.loads(x) for x in Path(args.pairs).read_text().splitlines() if x.strip()]
    texts = [t for p in pairs for t in (p["a"], p["b"])]
    out: dict = {"embed_model": args.embed_model}
    try:
        started = time.perf_counter()
        vecs = [embed(args.ollama, args.embed_model, [t])[0] for t in texts]   # one at a time: per-chunk time
        out["embed_ms_per_chunk"] = round((time.perf_counter() - started) * 1000 / len(texts), 1)
        sims = {"paraphrase": [], "unrelated": []}
        for i, p in enumerate(pairs):
            sims[p["kind"]].append(cos(vecs[2 * i], vecs[2 * i + 1]))
        out["paraphrase_pairs"], out["unrelated_pairs"] = len(sims["paraphrase"]), len(sims["unrelated"])
        out["paraphrase_cos_mean"] = round(statistics.mean(sims["paraphrase"]), 4)
        out["unrelated_cos_mean"] = round(statistics.mean(sims["unrelated"]), 4)
        out["gap"] = round(out["paraphrase_cos_mean"] - out["unrelated_cos_mean"], 4)
        a, b = embed(args.ollama, args.embed_model, [texts[0]])[0], embed(args.ollama, args.embed_model, [texts[0]])[0]
        out["determinism_max_abs_diff"] = max(abs(x - y) for x, y in zip(a, b))
    except Exception as exc:   # no Ollama reachable: say so, do not invent numbers
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


# ----------------------------------------------------------------------------- end to end
def ask(client: httpx.Client, api: str, q: str) -> tuple[dict, float]:
    t = time.perf_counter()
    r = client.post(f"{api.rstrip('/')}/api/ask", json={"question": q},
                    headers={"X-Cache-Bypass": "1"})
    r.raise_for_status()
    return r.json(), time.perf_counter() - t


def context_from_trace(traces: Path | None, rid: str) -> str | None:
    if not traces or not traces.exists():
        return None
    for f in sorted(traces.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines()[::-1][:5000]:
            if rid in line:
                rec = json.loads(line)
                if rec.get("trace_id") == rid and rec.get("prompt"):
                    return rec["prompt"][-1]["content"].split("\n\nQuestion:")[0]
    return None


def judge(args: argparse.Namespace, context: str, answer: str) -> bool | None:
    prompt = ("You check whether an ANSWER is fully supported by the CONTEXT. Answer only with JSON "
              '{"supported": true} if every claim in the ANSWER can be found in the CONTEXT, otherwise '
              '{"supported": false}.\n\nCONTEXT:\n' + context[:6000] + "\n\nANSWER:\n" + answer)
    try:
        r = httpx.post(f"{args.ollama}/api/chat", timeout=180, json={
            "model": args.judge_model, "stream": False, "format": "json",
            "messages": [{"role": "user", "content": prompt}],
            "options": {"temperature": 0, "seed": args.seed}})
        r.raise_for_status()
        return bool(json.loads(r.json()["message"]["content"]).get("supported"))
    except Exception:
        return None


def run_once(args: argparse.Namespace, golden: list[dict], client: httpx.Client, noise: bool) -> dict:
    rng = random.Random(args.seed)
    rows = []
    for q in golden:
        question = typo(q["question"], rng, args.typo_rate) if noise else q["question"]
        resp, secs = ask(client, args.api, question)
        rows.append({"q": q, "resp": resp, "secs": secs})
    ans = [r for r in rows if not r["q"]["must_abstain"]]
    un = [r for r in rows if r["q"]["must_abstain"]]
    ret = lambda r: r["resp"]["retrieved"]  # noqa: E731
    m = {
        "recall@3": mean([RE.recall_at_k(r["q"]["relevant"], ret(r), 3) for r in rows]),
        "recall@5": mean([RE.recall_at_k(r["q"]["relevant"], ret(r), 5) for r in rows]),
        "mrr": mean([mrr(r["q"]["relevant"], ret(r)) for r in rows]),
        "ndcg@5": mean([ndcg_at(r["q"]["relevant"], ret(r)) for r in rows]),
        "page_match@5": mean([page_match(r["q"]["relevant"], ret(r)) for r in rows]),
    }
    if noise:
        return {"metrics": m, "rows": rows}
    m["abstention_correctness"] = (sum(not r["resp"]["answered_from_context"] for r in un) / len(un)
                                   if un else None)
    m["false_abstention_rate"] = (sum(not r["resp"]["answered_from_context"] for r in ans) / len(ans)
                                  if ans else None)
    m["citation_validity"] = mean([RE.citation_validity(r["resp"]) for r in rows])
    lat = [r["secs"] for r in rows]
    m["latency_p50_s"], m["latency_p95_s"] = pct(lat, 50), pct(lat, 95)
    # faithfulness: judge every answer that claims to come from context
    flags = []
    for r in ans:
        if not r["resp"]["answered_from_context"]:
            continue
        ctx = context_from_trace(Path(args.traces) if args.traces else None, r["resp"]["request_id"])
        r["judge"] = judge(args, ctx, r["resp"]["answer"]) if (ctx and not args.no_judge) else None
        if r["judge"] is not None:
            flags.append(r["judge"])
    m["faithfulness"] = round(sum(flags) / len(flags), 4) if flags else None
    m["faithfulness_judged"] = len(flags)
    return {"metrics": m, "rows": rows}


def human_agreement(rows: list[dict], labels_path: Path) -> dict:
    if not labels_path.exists():
        return {"status": "no human labels yet: run with --label-sheet 10, label by hand, save "
                          f"{labels_path.name}"}
    labels = {j["id"]: j["supported"] for j in map(json.loads, labels_path.read_text().splitlines()) if j}
    pairs = [(labels[r["q"]["id"]], r["judge"]) for r in rows if r["q"]["id"] in labels and r.get("judge") is not None]
    if not pairs:
        return {"status": "labels found but none match judged answers"}
    return {"labelled": len(pairs), "agreement": round(sum(a == b for a, b in pairs) / len(pairs), 3)}


def label_sheet(rows: list[dict], n: int, traces: Path | None, out: Path) -> None:
    lines = ["# Label by hand: is the ANSWER fully supported by the CONTEXT?\n",
             "Save your labels as eval/human_labels.jsonl, one line each: "
             '`{"id": "q01", "supported": true}`\n']
    done = 0
    for r in rows:
        if r["q"]["must_abstain"] or not r["resp"]["answered_from_context"] or done >= n:
            continue
        ctx = context_from_trace(traces, r["resp"]["request_id"]) or "(trace not found)"
        lines += [f"\n## {r['q']['id']}: {r['q']['question']}\n", f"**Answer:** {r['resp']['answer']}\n",
                  f"<details><summary>context</summary>\n\n```\n{ctx}\n```\n</details>\n"]
        done += 1
    out.write_text("\n".join(lines), encoding="utf-8")


# ----------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default=os.environ.get("API_URL"), required="API_URL" not in os.environ)
    ap.add_argument("--host", help="Host header when going through the Ingress")
    ap.add_argument("--golden", default=str(HERE / "golden.jsonl"))
    ap.add_argument("--stage", default=os.environ.get("STAGE", "E4"), choices=list(STAGES),
                    help="A: baseline corpus only; B: + Batch B; E4: + questions added in E4")
    ap.add_argument("--label", default=os.environ.get("LABEL", "run"))
    ap.add_argument("--out-dir", default=os.environ.get("RESULTS_DIR", str(HERE / "results")))
    ap.add_argument("--traces", default=os.environ.get("TRACE_DIR"), help="trace folder (for the judge)")
    ap.add_argument("--pairs", default=str(HERE / "embedding_pairs.jsonl"))
    ap.add_argument("--human-labels", default=str(HERE / "human_labels.jsonl"))
    ap.add_argument("--ollama", default=os.environ.get("OLLAMA_URL", "http://host.minikube.internal:11434"))
    ap.add_argument("--embed-model", default=os.environ.get("EMBED_MODEL", "nomic-embed-text"))
    ap.add_argument("--judge-model", default=os.environ.get("JUDGE_MODEL", os.environ.get("LLM_MODEL", "llama3.2:1b")))
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--typo-rate", type=float, default=0.15)
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--no-module", action="store_true")
    ap.add_argument("--label-sheet", type=int, default=0, metavar="N")
    args = ap.parse_args()

    random.seed(args.seed)
    golden = load_golden(Path(args.golden), args.stage)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    headers = {"Host": args.host} if args.host else {}
    started = datetime.now(timezone.utc)
    print(f"suite '{args.label}': {len(golden)} questions, stage {args.stage}, {args.runs} runs", flush=True)

    with httpx.Client(timeout=900, headers=headers) as client:
        ready = client.get(f"{args.api.rstrip('/')}/readyz").json()
        runs = []
        for i in range(args.runs):
            print(f"  run {i + 1}/{args.runs} ...", flush=True)
            runs.append(run_once(args, golden, client, noise=False))
        print("  noise test (typos in queries) ...", flush=True)
        noisy = run_once(args, golden, client, noise=True)

    base = runs[0]["metrics"]
    if args.label_sheet:
        label_sheet(runs[0]["rows"], args.label_sheet, Path(args.traces) if args.traces else None,
                    out_dir / "label_sheet.md")
    result = {
        "label": args.label, "timestamp": started.isoformat(), "stage": args.stage,
        "questions": len(golden), "api": args.api, "index": ready.get("index"), "seed": args.seed,
        "module": {} if args.no_module else module_level(args),
        "component": {k: base[k] for k in ("recall@3", "recall@5", "mrr", "ndcg@5", "page_match@5")},
        "noise_typos": {"typo_rate": args.typo_rate, "metrics": noisy["metrics"],
                        "delta": {k: (None if base[k] is None or noisy["metrics"][k] is None
                                      else round(noisy["metrics"][k] - base[k], 4))
                                  for k in noisy["metrics"]}},
        "end_to_end": {k: base[k] for k in base if k not in ("recall@3", "recall@5", "mrr", "ndcg@5", "page_match@5")},
        "judge_vs_human": human_agreement(runs[0]["rows"], Path(args.human_labels)),
        "stochasticity": {"runs": args.runs, "note": "generation seed fixed on the API (LLM_SEED); "
                          "latency varies with machine load; retrieval is deterministic",
                          "diff_run2_minus_run1": {k: (None if v is None or runs[-1]["metrics"].get(k) is None
                                                       else round(runs[-1]["metrics"][k] - v, 4))
                                                   for k, v in base.items()}},
        "per_question": [{"id": r["q"]["id"], "kind": r["q"]["kind"], "hard": r["q"]["hard"],
                          "origin": r["q"]["origin"], "answered": r["resp"]["answered_from_context"],
                          "top_chunks": [(t["source"], t["section"], round(t["score"], 3)) for t in r["resp"]["retrieved"][:3]],
                          "recall@5": RE.recall_at_k(r["q"]["relevant"], r["resp"]["retrieved"], 5),
                          "judge": r.get("judge"), "seconds": round(r["secs"], 2),
                          "request_id": r["resp"]["request_id"],
                          "differs_between_runs": r["resp"]["answer"] != runs[-1]["rows"][i]["resp"]["answer"]}
                         for i, r in enumerate(runs[0]["rows"])],
    }
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"{stamp}_{args.label}.json"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    (out_dir / f"{args.label}-latest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (out_dir / f"{stamp}_{args.label}.md").write_text(summary_md(result), encoding="utf-8")
    print("\n" + summary_md(result))
    print(f"result file: {path}")
    return 0


def summary_md(r: dict) -> str:
    f = lambda v: "n/a" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))  # noqa: E731
    m, c, e, n = r["module"], r["component"], r["end_to_end"], r["noise_typos"]
    rows = [("MODULE", "embedding", ""),
            ("", "paraphrase cos (mean)", f(m.get("paraphrase_cos_mean"))),
            ("", "unrelated cos (mean)", f(m.get("unrelated_cos_mean"))),
            ("", "gap", f(m.get("gap"))),
            ("", "embed ms / chunk", f(m.get("embed_ms_per_chunk"))),
            ("", "determinism, max abs diff", f(m.get("determinism_max_abs_diff"))),
            ("COMPONENT", "retrieval", "")]
    rows += [("", k, f(v)) for k, v in c.items()]
    rows += [("", f"{k} with typos (delta)", f"{f(n['metrics'][k])} ({f(n['delta'][k])})") for k in c]
    rows += [("END-TO-END", "answers", "")] + [("", k, f(v)) for k, v in e.items()]
    rows += [("JUDGE", "agreement with human", f(r["judge_vs_human"].get("agreement", r["judge_vs_human"].get("status"))))]
    idx = r.get("index") or {}
    head = (f"## Suite `{r['label']}`  {r['timestamp']}\n\ncollection `{idx.get('collection')}`, "
            f"embed_version `{idx.get('embed_version')}`, chunk_size `{idx.get('chunk_size')}`, "
            f"top_k `{idx.get('top_k')}`; {r['questions']} questions, stage {r['stage']}\n\n")
    body = "| level | metric | value |\n|---|---|---|\n" + "\n".join(f"| {a} | {b} | {c_} |" for a, b, c_ in rows)
    return head + body + "\n"


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""D2: print the exact context and prompt that produced an answer.

    python -m app.tools.trace_show <trace_id>                 # inside a pod: kubectl exec deploy/api -- ...
    python -m app.tools.trace_show <trace_id> --dir ./traces  # on a laptop, against copied files
    python -m app.tools.trace_show <trace_id> --json          # the raw record
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys


def find(trace_id: str, directory: str) -> dict | None:
    for path in sorted(glob.glob(os.path.join(directory, "*.jsonl"))):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if trace_id in line:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if rec.get("trace_id") == trace_id:
                        return rec
    return None


def render(r: dict) -> str:
    out = [f"TRACE {r['trace_id']}   {r['ts']}   outcome={r['outcome']}   cache={r['cache']}",
           f"query:       {r['query']}",
           f"index:       collection={r['collection']['name']} index_id={r['collection']['index_id']} "
           f"chunk_size={r['collection']['chunk_size']}  embedding={r['embedding']['model']}"
           f"@{r['embedding']['version']}",
           f"model:       {r['model']['provider']} {r['model']['name']} {r['model']['params']}",
           f"filters:     {r['filters']}",
           f"latency ms:  {r['latency_ms']}",
           f"guardrails:  {r['guardrails'] or 'none'}",
           f"reranked:    {r['reranked_order']}", "", "RETRIEVED (rank, score, doc@version, chunk, section, page)"]
    for i, c in enumerate(r["retrieved"], 1):
        out.append(f"  {i}. {c['score']:.3f}  {c['source']}@{c['doc_version']}  {c['chunk_id']}  "
                   f"[{c['section']}] p.{c['page']}")
    out.append("")
    if r.get("prompt"):
        out.append(f"PROMPT (hash {r['prompt_hash']})")
        for m in r["prompt"]:
            out.append(f"--- {m['role']} ---\n{m['content']}")
    else:
        out.append("PROMPT: none (answered from cache, or abstained before any model call)")
    out += ["", "RESPONSE:", r["response"], f"citations: {r['citations']}"]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("trace_id")
    ap.add_argument("--dir", default=os.environ.get("TRACE_DIR", "/data/traces"))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    rec = find(a.trace_id, a.dir)
    if rec is None:
        print(f"trace {a.trace_id} not found in {a.dir}", file=sys.stderr)
        return 1
    print(json.dumps(rec, indent=1, ensure_ascii=False) if a.json else render(rec))
    return 0


if __name__ == "__main__":
    sys.exit(main())

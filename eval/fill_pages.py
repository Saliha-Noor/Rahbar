#!/usr/bin/env python3
"""Fill the ground-truth `page` of golden questions from the index itself.

    kubectl port-forward -n rahbar svc/chroma 8000:8000 &
    python eval/fill_pages.py --chroma localhost:8000

For each (source, section) in golden.jsonl with page null, find the first chunk of that source whose
section matches (same prefix rule as run_eval.py) and copy its page. CHECK the result by hand
against the PDF: the page is where the section STARTS.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("--chroma", default="localhost:8000")
ap.add_argument("--collection", default="rahbar")
ap.add_argument("--golden", default=str(HERE / "golden.jsonl"))
a = ap.parse_args()

import chromadb  # noqa: E402  (chromadb-client)

host, _, port = a.chroma.partition(":")
col = chromadb.HttpClient(host=host, port=int(port or 8000)).get_collection(a.collection)
rows = [json.loads(x) for x in Path(a.golden).read_text().splitlines() if x.strip()]
filled = missing = 0
for r in rows:
    for rel in r["relevant"]:
        if rel.get("page") is not None:
            continue
        got = col.get(where={"source": rel["source"]}, include=["metadatas"])
        pages = sorted(m["page"] for m in got["metadatas"]
                       if re.match(re.escape(rel["section"].lower()) + r"(?!\d)", m["section"].lower()))
        if pages:
            rel["page"], filled = pages[0], filled + 1
        else:
            missing += 1
            print(f"no chunk found for {r['id']}: {rel['source']} / {rel['section']}", file=sys.stderr)
Path(a.golden).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
print(f"filled {filled} pages, {missing} not found")

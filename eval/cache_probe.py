"""Cosine similarity of question pairs, to choose CACHE_THRESHOLD (section 3.3).

Edit PAIRS for your corpus: paraphrases that SHOULD share a cached answer (True) and
near-misses that must NOT (False). Choose the lowest threshold with zero false hits, and
record the false hit that ruled a lower value out in docs/PIPELINE.md.

    python eval/cache_probe.py [--ollama http://localhost:11434] [--model nomic-embed-text]
"""

from __future__ import annotations

import argparse
import math

import httpx

PAIRS = [
    ("What CGPA puts a student on academic warning?", "Which CGPA means I get an academic warning?", True),
    ("What is the minimum attendance to sit the exam?", "How much attendance do I need for the final exam?", True),
    ("Can I repeat a course?", "Can I withdraw from a course?", False),
    ("What is the fee per credit hour?", "What is the refund timeline?", False),
]


def cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ollama", default="http://localhost:11434")
    ap.add_argument("--model", default="nomic-embed-text")
    args = ap.parse_args()

    def emb(text: str) -> list[float]:
        r = httpx.post(f"{args.ollama}/api/embed",
                       json={"model": args.model, "input": text}, timeout=60)
        r.raise_for_status()
        return r.json()["embeddings"][0]

    same_scores, diff_scores = [], []
    
    for a, b, same in PAIRS:
        s = cos(emb(a), emb(b))
        (same_scores if same else diff_scores).append(s)
        print(f"{s:.3f}  should_share={same!s:<5} | {a}  <->  {b}")
        
    if same_scores and diff_scores:
        print(f"\nlowest paraphrase: {min(same_scores):.3f}   highest near-miss: {max(diff_scores):.3f}")
        print("CACHE_THRESHOLD must be above the near-miss and at or below the paraphrases")

if __name__ == "__main__":
    main()

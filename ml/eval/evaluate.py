"""Measure search quality on the hand-labeled 6.006 questions.

Each label is a time range in a lecture ("Dijkstra's correctness proof is at
39:57-46:16 in lecture 13"). A result counts as relevant if the second it jumps
to lands inside a labeled range (with 15 s of slack either side). Ranges, not
segment ids, so the labels survive re-chunking or re-transcribing.

  python ml/eval/evaluate.py --split test --out ml/eval/results.json
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

from lecturelens.db import connection
from lecturelens.search.engine import collapse, fuse, hydrate, retrieve
from lecturelens.search.metrics import evaluate

HERE = Path(__file__).parent
SLACK_S = 15.0


def load_queries(split: str | None) -> list[dict]:
    rows = [json.loads(line) for line in (HERE / "queries.jsonl").read_text().splitlines() if line]
    return [r for r in rows if split in (None, "all", r["split"])]


def course_and_lectures(code: str = "6.006") -> tuple[str, dict]:
    with connection() as conn:
        cid = conn.execute("SELECT id FROM courses WHERE code = %s AND public", (code,)).fetchone()
        if cid is None:
            sys.exit("demo course not loaded; run scripts/seed_demo.py first")
        lecs = conn.execute(
            "SELECT id, position FROM lectures WHERE course_id = %s", (cid["id"],)
        ).fetchall()
    return cid["id"], {r["id"]: r["position"] for r in lecs}


def judge(query: dict, hits: list, positions: dict) -> tuple[list[str], dict[str, int]]:
    """Turn hits into ids + graded relevance. Two hits on the same labeled range only
    count once, so a method can't score by repeating itself."""
    rel = {f"L{i}": lab["rel"] for i, lab in enumerate(query["labels"])}
    ranked, seen = [], set()
    for n, h in enumerate(hits):
        pos = positions.get(h.lecture_id)
        match = None
        for i, lab in enumerate(query["labels"]):
            if lab["lecture"] == pos and lab["start"] - SLACK_S <= h.jump_s <= lab["end"] + SLACK_S:
                if match is None or lab["rel"] > rel[match]:
                    match = f"L{i}"
        key = match if match and match not in seen else f"miss{n}"
        seen.add(key)
        ranked.append(key)
    return ranked, rel


def run(methods: list[str], queries: list[dict], limit: int = 10) -> dict:
    course, positions = course_and_lectures()
    results = {}
    for method in methods:
        runs, qrels, latencies = {}, {}, []
        for q in queries:
            t0 = time.perf_counter()
            ranked = fuse(retrieve(q["query"], [course], method))
            hits = hydrate(q["query"], collapse(ranked, limit))
            latencies.append(time.perf_counter() - t0)
            runs[q["id"]], qrels[q["id"]] = judge(q, hits, positions)
        scores = evaluate(runs, qrels, ks=(1, 5, 10))
        scores["p50_ms"] = float(np.percentile(latencies, 50) * 1000)
        results[method] = scores
    return results


def table(results: dict) -> str:
    cols = ["hit@1", "hit@5", "recall@5", "mrr", "ndcg@10", "p50_ms"]
    lines = ["| method | " + " | ".join(cols) + " |", "|---" * (len(cols) + 1) + "|"]
    for m, s in results.items():
        cells = [f"{s[c]:.0f}" if c == "p50_ms" else f"{s[c]:.3f}" for c in cols]
        lines.append(f"| {m} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test", choices=["test", "val", "all"])
    ap.add_argument(
        "--methods", nargs="+", default=["keyword", "meaning", "visual", "text", "hybrid"]
    )
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    queries = load_queries(args.split)
    results = run(args.methods, queries)
    print(f"{len(queries)} queries ({args.split})\n")
    print(table(results))
    if args.out:
        args.out.write_text(
            json.dumps({"split": args.split, "n": len(queries), "results": results}, indent=2)
        )


if __name__ == "__main__":
    main()

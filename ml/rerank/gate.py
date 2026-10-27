"""Regression gate for the re-ranker. A new model only replaces the old one if, on
the held-out test questions, it beats both baselines (plain hybrid and the logistic
regression) and doesn't score worse than the model it replaces.

    python ml/rerank/gate.py            # check (CI runs this through pytest)
    python ml/rerank/gate.py --accept   # after retraining + re-running the eval

The eval needs the processed demo course, so CI checks the committed results files
rather than re-running search. Retraining without updating them fails the
weights-match test in backend/tests/test_rerank.py.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "ml/eval/results_test.json"
ACCEPTED = ROOT / "ml/rerank/accepted.json"
TRAIN = ROOT / "ml/rerank/train_results.json"
METRICS = ("ndcg@10", "recall@5", "mrr")
TOLERANCE = 0.005  # eval noise is zero (deterministic), this only absorbs rounding


def check(results: dict, accepted: dict | None) -> list[str]:
    r = results["results"]
    new = r["hybrid+reranker"]
    problems = []
    for base in ("hybrid", "hybrid+lr"):
        if new["ndcg@10"] <= r[base]["ndcg@10"]:
            problems.append(
                f"re-ranker NDCG@10 {new['ndcg@10']:.3f} <= {base} {r[base]['ndcg@10']:.3f}"
            )
    if accepted:
        for m in METRICS:
            if new[m] < accepted["test"][m] - TOLERANCE:
                problems.append(f"{m} fell from {accepted['test'][m]:.3f} to {new[m]:.3f}")
    return problems


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--accept", action="store_true")
    args = ap.parse_args()
    results = json.loads(RESULTS.read_text())
    accepted = json.loads(ACCEPTED.read_text()) if ACCEPTED.exists() else None
    problems = check(results, accepted)
    for p in problems:
        print("FAIL:", p)
    if problems:
        sys.exit(1)
    if args.accept:
        new = results["results"]["hybrid+reranker"]
        ACCEPTED.write_text(
            json.dumps(
                {
                    "model_version": json.loads(TRAIN.read_text())["version"],
                    "date": results["date"],
                    "test": {m: round(new[m], 4) for m in METRICS},
                },
                indent=2,
            )
            + "\n"
        )
        print(f"accepted: {ACCEPTED}")
    else:
        print("gate passed")


if __name__ == "__main__":
    main()

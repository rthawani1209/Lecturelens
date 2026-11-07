"""Regression gate for the re-ranker. A new model only replaces the old one if, on
the held-out test questions, it finds more right moments in the top 5 than plain
hybrid and the logistic regression without ranking worse (NDCG@10 within
TOLERANCE), and doesn't score worse than the model it replaces. It also checks that the default
search mode isn't beaten by any single retriever.

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
# a run is deterministic, but re-indexing the course shifts NDCG by a few thousandths
TOLERANCE = 0.005


# what /search uses when no mode is given; must match Settings.search_mode
DEFAULT = "meaning"
SINGLE = ("keyword", "meaning", "visual")


def check(results: dict, accepted: dict | None) -> list[str]:
    r = results["results"]
    problems = []
    # the default search must not lose to any single retriever on its own
    for base in SINGLE:
        if r[DEFAULT]["ndcg@10"] < r[base]["ndcg@10"]:
            problems.append(
                f"default ({DEFAULT}) NDCG@10 {r[DEFAULT]['ndcg@10']:.3f} < {base}"
                f" {r[base]['ndcg@10']:.3f}"
            )
    # the re-ranker must beat its own baselines on what it's for (recall@5), and
    # not rank worse while doing it...
    new = r["hybrid+reranker"]
    for base in ("hybrid", "hybrid+lr"):
        if new["recall@5"] <= r[base]["recall@5"]:
            problems.append(
                f"re-ranker recall@5 {new['recall@5']:.3f} <= {base} {r[base]['recall@5']:.3f}"
            )
        if new["ndcg@10"] < r[base]["ndcg@10"] - TOLERANCE:
            problems.append(
                f"re-ranker NDCG@10 {new['ndcg@10']:.3f} < {base} {r[base]['ndcg@10']:.3f}"
            )
    # ...and not get worse than the model it replaces
    if accepted:
        for m in METRICS:
            if new[m] < accepted["test"][m] - TOLERANCE:
                problems.append(f"{m} fell from {accepted['test'][m]:.3f} to {new[m]:.3f}")
    return problems


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--accept", action="store_true")
    # only when the eval setup itself changed (fusion weights, candidate pool), so old
    # and new numbers aren't comparable; say why in the commit message
    ap.add_argument("--new-baseline", action="store_true")
    args = ap.parse_args()
    results = json.loads(RESULTS.read_text())
    accepted = None
    if ACCEPTED.exists() and not args.new_baseline:
        accepted = json.loads(ACCEPTED.read_text())
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

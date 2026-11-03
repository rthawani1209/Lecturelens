"""Grid-search the RRF weights on the val questions (never test).

python ml/eval/tune_rrf.py
"""

import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from evaluate import load_queries, run  # noqa: E402

from lecturelens.search import engine  # noqa: E402


def main() -> None:
    queries = load_queries("val")
    rows = []
    for kw, ocr, vis in itertools.product((0.25, 0.5, 1.0), (0.0, 0.4, 0.8), (0.0, 0.3, 0.6)):
        engine.WEIGHTS.update({"keyword": kw, "meaning": 1.0, "ocr": ocr, "visual": vis})
        s = run(["hybrid"], queries)["hybrid"]
        rows.append(
            {
                "keyword": kw,
                "ocr": ocr,
                "visual": vis,
                "ndcg@10": s["ndcg@10"],
                "recall@5": s["recall@5"],
                "mrr": s["mrr"],
            }
        )
        print(json.dumps(rows[-1]), flush=True)
    best = max(rows, key=lambda r: r["ndcg@10"])
    print("best on val:", json.dumps(best))
    out = Path(__file__).parent / "rrf_tuning_val.json"
    out.write_text(json.dumps({"best": best, "grid": rows}, indent=2) + "\n")


if __name__ == "__main__":
    main()

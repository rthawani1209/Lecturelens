"""Where to cut off search so nonsense queries come back empty.

Meaning search always returns its nearest sentences, even for "xqzvbnm wibble".
This finds the lowest similarity any relevant hit has across every labeled
question (all three courses), and the best similarity a set of off-topic and
gibberish queries reach on 6.006. The floor in config.py sits between the two.
Results below it are dropped after ranking, so meaning search's numbers can't
change. It also reports how many results each mode still returns for the
nonsense queries (the gate in engine._gate: hybrid needs meaning above the floor
or every query word in the speech or on a slide).

  python ml/eval/meaning_floor.py --out ml/eval/meaning_floor.json
"""

import argparse
import json
from pathlib import Path

import evaluate as ev

from lecturelens.config import get_settings
from lecturelens.search.engine import collapse, fuse, hydrate, retrieve, search

JUNK = [
    "xqzvbnm wibble",
    "asdf qwerty zxcv",
    "kjhg lkjh poiu",
    "purple monkey dishwasher",
    "lorem ipsum dolor sit amet",
    "best pizza in new york",
    "taylor swift tour dates",
    "how to fix a flat bike tire",
    "weather tomorrow",
    "banana bread recipe",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    floor = get_settings().meaning_floor
    get_settings().meaning_floor = 0.0  # measure without the cut

    relevant = []
    for code in ["6.006", "6.100L", "18.06"]:
        course, positions = ev.course_and_lectures(code)
        for q in ev.load_queries("all", code):
            ranked = collapse(fuse(retrieve(q["query"], [course], "meaning")), 10)
            keys, _ = ev.judge(q, hydrate(q["query"], ranked), positions)
            for key, (c, _) in zip(keys, ranked, strict=True):
                if not key.startswith("miss"):
                    relevant.append(
                        {
                            "course": code,
                            "query": q["query"],
                            "score": c.scores["meaning"],
                        }
                    )

    course, _ = ev.course_and_lectures("6.006")
    junk = []
    for q in JUNK:
        cands = retrieve(q, [course], "meaning")
        junk.append({"query": q, "best": max(c.scores["meaning"] for c in cands.values())})

    get_settings().meaning_floor = floor
    returned = {
        m: {q: len(search(q, [course], mode=m)) for q in JUNK} for m in ("meaning", "hybrid")
    }

    relevant.sort(key=lambda r: r["score"])
    out = {
        "floor": floor,
        "lowest_relevant": relevant[:5],
        "relevant_hits": len(relevant),
        "relevant_below_floor": sum(r["score"] < floor for r in relevant),
        "junk": sorted(junk, key=lambda r: -r["best"]),
        "junk_above_floor": sum(r["best"] >= floor for r in junk),
        "junk_results_by_mode": returned,
    }
    print(json.dumps(out, indent=2))
    if args.out:
        args.out.write_text(json.dumps(out, indent=2) + "\n")


if __name__ == "__main__":
    main()

"""Build the re-ranker's training and evaluation data (run with the backend venv).

Training queries are generated from the transcripts and slides of the training
lectures, so no hand labels are spent on training. For each query we take the top
50 fused candidates the real search engine returns, compute their features and
mark the ones that come from the window the query was made from.

The hand-labeled questions (ml/eval/queries.jsonl) get the same treatment, so
training can stop early on the val split. The test lectures never produce
training queries.

    python ml/rerank/build_dataset.py --out ml/rerank/data/dataset.npz
"""

import argparse
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))
from evaluate import SLACK_S, course_and_lectures, load_queries  # noqa: E402

from lecturelens.db import connection  # noqa: E402
from lecturelens.embed import clip_embedder, text_embedder  # noqa: E402
from lecturelens.search import features  # noqa: E402
from lecturelens.search.engine import fuse, retrieve  # noqa: E402

TEST_LECTURES = {1, 4, 7, 10, 13, 16, 19}
TOP_N = 50


def idf_table(texts: list[str]) -> dict[str, float]:
    df = Counter(w for t in texts for w in features.words(t))
    n = len(texts)
    return {w: math.log(n / c) for w, c in df.items()}


def make_query(rng: random.Random, text: str, idf: dict[str, float]) -> str | None:
    """A short keyword-style query: the rarer words of a sentence, in their original order,
    with a random one dropped now and then so it isn't an exact copy."""
    toks = [w for w in features._WORD.findall(text.lower()) if w not in features.STOP]
    toks = [w for w in dict.fromkeys(toks) if len(w) > 2 and not w.isdigit()]
    if len(toks) < 3:
        return None
    k = rng.randint(3, min(6, len(toks)))
    keep = set(sorted(toks, key=lambda w: -idf.get(w, 0))[:k])
    q = [w for w in toks if w in keep]
    if len(q) > 3 and rng.random() < 0.3:
        q.pop(rng.randrange(len(q)))
    return " ".join(q)


def synthetic(rng: random.Random, per_lecture: int) -> list[dict]:
    with connection() as conn:
        segs = conn.execute(
            "SELECT s.id, s.lecture_id, s.start_s, s.end_s, s.text, l.position,"
            "       (SELECT string_agg(f.ocr_text, ' ') FROM frames f"
            "         WHERE f.lecture_id = s.lecture_id"
            "           AND f.t_s BETWEEN s.start_s - 5 AND s.end_s) AS ocr"
            "  FROM segments s JOIN lectures l ON l.id = s.lecture_id ORDER BY s.id"
        ).fetchall()
    idf = idf_table([s["text"] for s in segs])
    out = []
    by_lecture: dict[int, list[dict]] = {}
    for s in segs:
        if s["position"] not in TEST_LECTURES:
            by_lecture.setdefault(s["position"], []).append(s)
    for pos, rows in sorted(by_lecture.items()):
        for s in rng.sample(rows, min(per_lecture, len(rows))):
            # mostly from what was said, sometimes from what was on the slide
            src = (
                s["ocr"]
                if s["ocr"] and len(features.words(s["ocr"])) >= 4 and rng.random() < 0.25
                else s["text"]
            )
            q = make_query(rng, src, idf)
            if q:
                out.append(
                    {
                        "query": q,
                        "lecture": pos,
                        "start": s["start_s"],
                        "end": s["end_s"],
                        "split": "train",
                        "kind": "synthetic",
                    }
                )
    return out


def label(c, lab_lecture: int, start: float, end: float, positions: dict, slack: float) -> int:
    if positions.get(c.lecture_id) != lab_lecture:
        return 0
    return int(c.start_s < end + slack and c.end_s > start - slack)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-lecture", type=int, default=80)
    ap.add_argument("--seed", type=int, default=6006)
    ap.add_argument("--out", type=Path, default=Path("ml/rerank/data/dataset.npz"))
    args = ap.parse_args()
    rng = random.Random(args.seed)
    course, positions = course_and_lectures()

    queries = synthetic(rng, args.per_lecture)
    for h in load_queries("all"):
        queries.append(
            {
                "query": h["query"],
                "labels": h["labels"],
                "split": h["split"],
                "kind": "hand",
                "id": h["id"],
            }
        )

    temb, cemb = text_embedder(), clip_embedder()
    X, y, qid, meta = [], [], [], []
    skipped = 0
    for n, q in enumerate(queries):
        ranked = fuse(retrieve(q["query"], [course], "hybrid"))[:TOP_N]
        if not ranked:
            skipped += 1
            continue
        if q["kind"] == "synthetic":
            rel = [label(c, q["lecture"], q["start"], q["end"], positions, 0.0) for c, _ in ranked]
        else:
            rel = [
                max(
                    [
                        lab["rel"]
                        * label(c, lab["lecture"], lab["start"], lab["end"], positions, SLACK_S)
                        for lab in q["labels"]
                    ]
                )
                for c, _ in ranked
            ]
        # a synthetic query whose source never made the top 50 teaches nothing
        if q["kind"] == "synthetic" and not any(rel):
            skipped += 1
            continue
        f = features.build(
            q["query"], ranked, temb.embed([q["query"]])[0], cemb.embed_texts([q["query"]])[0]
        )
        X.append(f)
        y.append(np.array(rel, np.float32))
        qid.append(np.full(len(ranked), len(meta)))
        meta.append({k: v for k, v in q.items() if k != "labels"})
        if n % 100 == 0:
            print(f"{n}/{len(queries)} queries", flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.out,
        X=np.concatenate(X),
        y=np.concatenate(y),
        qid=np.concatenate(qid),
        features=np.array(features.FEATURES),
    )
    args.out.with_suffix(".json").write_text(json.dumps(meta, indent=1))
    splits = Counter(m["split"] for m in meta)
    print(
        f"kept {len(meta)} queries {dict(splits)}, skipped {skipped}, rows {sum(len(a) for a in y)}"
    )


if __name__ == "__main__":
    main()

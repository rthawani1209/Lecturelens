"""Features for re-ranking the top fused candidates, built with NumPy.

One row per candidate window. Retriever scores only exist for the lists a window
showed up in, so the vector-based ones are recomputed for every candidate here:
that way "meaning similarity" is always filled in, not just for the meaning top 50.
"""

import re

import numpy as np

from ..db import connection
from .engine import Candidate

TAGS = ["slide", "code", "whiteboard", "diagram", "professor", "other"]

# words that say which kind of frame the person is looking for
TAG_WORDS = {
    "slide": {"slide", "slides", "table", "chart", "powerpoint"},
    "code": {"code", "python", "pseudocode", "program", "implementation", "implement"},
    "whiteboard": {"board", "chalkboard", "blackboard", "whiteboard", "wrote", "written", "write"},
    "diagram": {"diagram", "drawing", "drew", "draw", "picture", "figure"},
    "professor": {"professor", "instructor", "joke", "story", "demo", "says"},
    "other": set(),
}

FEATURES = [
    "keyword_score",  # ts_rank_cd, 0 if the keyword retriever missed it
    "keyword_rrf",  # 1/(60+rank) in each list, 0 if absent
    "meaning_rrf",
    "ocr_rrf",
    "visual_rrf",
    "fused_score",  # weighted RRF from the engine
    "meaning_sim",  # query vs window, MiniLM cosine
    "best_line_sim",  # query vs the closest single sentence in the window
    "visual_sim",  # query (CLIP text) vs best frame in the window (CLIP image)
    "term_overlap",  # share of the query's words that appear in the window text
    "ocr_overlap",  # same, against text read off the slides in the window
    "tag_match",  # tag score of the frame type the query asks for (0 if it doesn't ask)
    *(f"tag_{t}" for t in TAGS),  # what the window shows
    "position",  # start time / lecture length
    "first_two_minutes",  # intros mention everything and explain nothing
    "n_retrievers",  # how many lists found it
]

_WORD = re.compile(r"[a-z0-9]+")
STOP = set(
    "a an and are as at be but by can do does for from has have how i if in into is it its of"
    " on or so that the their then there these this to was we what when where which while who"
    " why will with you your".split()
)


def words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in STOP and len(w) > 1}


def _overlap(q: set[str], text: str) -> float:
    if not q:
        return 0.0
    t = words(text)
    # count "sorting" in the window for a query that says "sort"
    return sum(1 for w in q if w in t or any(x.startswith(w) for x in t)) / len(q)


def _vec(v) -> np.ndarray:
    return v.to_numpy() if hasattr(v, "to_numpy") else np.asarray(v, np.float32)


def build(
    q: str,
    ranked: list[tuple[Candidate, float]],
    qvec: np.ndarray,
    qclip: np.ndarray,
    k: int = 60,
) -> np.ndarray:
    """Feature matrix (len(ranked), len(FEATURES)) for the candidates, in order."""
    if not ranked:
        return np.zeros((0, len(FEATURES)), np.float32)
    seg_ids = [c.segment_id for c, _ in ranked]
    lec_ids = list({c.lecture_id for c, _ in ranked})
    with connection() as conn:
        segs = {
            r["id"]: r
            for r in conn.execute(
                "SELECT id, text, text_emb FROM segments WHERE id = ANY(%s)", (seg_ids,)
            )
        }
        dur = {
            r["id"]: r["duration_s"] or 1.0
            for r in conn.execute(
                "SELECT id, duration_s FROM lectures WHERE id = ANY(%s)", (lec_ids,)
            )
        }
        # every transcript line and frame that falls inside one of the windows
        lines = conn.execute(
            """
            SELECT s.id AS seg, t.text_emb FROM segments s
              JOIN transcript_lines t ON t.lecture_id = s.lecture_id
                   AND t.start_s < s.end_s AND t.end_s > s.start_s
             WHERE s.id = ANY(%s) AND t.text_emb IS NOT NULL
            """,
            (seg_ids,),
        ).fetchall()
        frames = conn.execute(
            """
            SELECT s.id AS seg, f.clip_emb, f.ocr_text, f.tag_scores FROM segments s
              JOIN frames f ON f.lecture_id = s.lecture_id
                   AND f.t_s BETWEEN s.start_s - 5 AND s.end_s
             WHERE s.id = ANY(%s)
            """,
            (seg_ids,),
        ).fetchall()

    best_line: dict[int, float] = {}
    if lines:
        sims = np.stack([_vec(r["text_emb"]) for r in lines]) @ qvec
        for r, s in zip(lines, sims, strict=True):
            best_line[r["seg"]] = max(best_line.get(r["seg"], -1.0), float(s))
    by_seg: dict[int, list[dict]] = {}
    for r in frames:
        by_seg.setdefault(r["seg"], []).append(r)

    qwords = words(q)
    wanted = [t for t in TAGS if qwords & TAG_WORDS[t]]
    out = np.zeros((len(ranked), len(FEATURES)), np.float32)
    for i, (c, fused) in enumerate(ranked):
        seg = segs[c.segment_id]
        fr = by_seg.get(c.segment_id, [])
        vis = [float(_vec(f["clip_emb"]) @ qclip) for f in fr if f["clip_emb"] is not None]
        tags = np.zeros(len(TAGS), np.float32)
        for f in fr:
            if f["tag_scores"]:
                tags += np.array([f["tag_scores"].get(t, 0.0) for t in TAGS], np.float32)
        if fr:
            tags /= len(fr)
        row = [
            c.scores.get("keyword", 0.0),
            *(
                1.0 / (k + c.ranks[n]) if n in c.ranks else 0.0
                for n in ("keyword", "meaning", "ocr", "visual")
            ),
            fused,
            float(_vec(seg["text_emb"]) @ qvec) if seg["text_emb"] is not None else 0.0,
            best_line.get(c.segment_id, 0.0),
            max(vis) if vis else 0.0,
            _overlap(qwords, seg["text"]),
            _overlap(qwords, " ".join(f["ocr_text"] for f in fr)),
            sum(tags[TAGS.index(t)] for t in wanted),
            *tags,
            c.start_s / dur[c.lecture_id],
            float(c.start_s < 120),
            len(c.ranks),
        ]
        out[i] = row
    return out

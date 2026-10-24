"""Hybrid search over lectures.

Four retrievers each return their top candidates:

  keyword   Postgres full-text over transcript windows      (exact words)
  meaning   pgvector cosine over MiniLM window vectors       (paraphrases)
  ocr       Postgres full-text over text read off slides     (what was written)
  visual    pgvector cosine over CLIP frame vectors          (what it looked like)

Frame hits are mapped onto the transcript window that covers them, so everything
is ranked in one currency: a moment = (lecture, window). The lists are merged with
reciprocal rank fusion, nearby windows are collapsed into one result, and each
result gets the best matching sentence to jump to plus a thumbnail.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

import numpy as np

from ..config import get_settings
from ..db import connection
from .fusion import group_by_time, rrf

MODES = {
    "hybrid": ("keyword", "meaning", "ocr", "visual"),
    "text": ("keyword", "meaning"),
    "visual": ("ocr", "visual"),
    "keyword": ("keyword",),
    "meaning": ("meaning",),
}
# visual matches are noisier (CLIP on 360p lecture video), so they count a bit less
WEIGHTS = {"keyword": 1.0, "meaning": 1.0, "ocr": 0.8, "visual": 0.6}


@dataclass
class Candidate:
    segment_id: int
    lecture_id: UUID
    start_s: float
    end_s: float
    ranks: dict[str, int] = field(default_factory=dict)
    scores: dict[str, float] = field(default_factory=dict)
    frame_id: int | None = None  # frame that matched, if a visual retriever found it


@dataclass
class Hit:
    lecture_id: UUID
    lecture_title: str
    course_id: UUID
    week: int | None
    start_s: float
    end_s: float
    jump_s: float
    text: str
    sentence: str
    frame_t: float | None
    thumb_key: str | None
    tag: str | None
    ocr_text: str
    score: float
    matched_by: list[str]
    segment_id: int


# OR the query's words together; ts_rank_cd still rewards windows that match more of them.
_TSQUERY = "replace(plainto_tsquery('english', %(q)s)::text, '&', '|')::tsquery"


def _keyword(conn, q: str, courses: Sequence[UUID], n: int) -> list[dict]:
    return conn.execute(
        f"""
        SELECT s.id AS segment_id, s.lecture_id, s.start_s, s.end_s,
               ts_rank_cd(s.tsv, {_TSQUERY}, 32) AS score
          FROM segments s JOIN lectures l ON l.id = s.lecture_id
         WHERE l.course_id = ANY(%(courses)s) AND s.tsv @@ {_TSQUERY}
         ORDER BY score DESC LIMIT %(n)s
        """,
        {"q": q, "courses": list(courses), "n": n},
    ).fetchall()


def _meaning(conn, vec: np.ndarray, courses: Sequence[UUID], n: int) -> list[dict]:
    return conn.execute(
        """
        SELECT s.id AS segment_id, s.lecture_id, s.start_s, s.end_s,
               1 - (s.text_emb <=> %(v)s) AS score
          FROM segments s JOIN lectures l ON l.id = s.lecture_id
         WHERE l.course_id = ANY(%(courses)s) AND s.text_emb IS NOT NULL
         ORDER BY s.text_emb <=> %(v)s LIMIT %(n)s
        """,
        {"v": vec, "courses": list(courses), "n": n},
    ).fetchall()


def _ocr(conn, q: str, courses: Sequence[UUID], n: int) -> list[dict]:
    return conn.execute(
        f"""
        SELECT f.id AS frame_id, f.lecture_id, f.t_s,
               ts_rank_cd(f.ocr_tsv, {_TSQUERY}, 32) AS score
          FROM frames f JOIN lectures l ON l.id = f.lecture_id
         WHERE l.course_id = ANY(%(courses)s) AND f.ocr_tsv @@ {_TSQUERY}
         ORDER BY score DESC LIMIT %(n)s
        """,
        {"q": q, "courses": list(courses), "n": n},
    ).fetchall()


def _visual(conn, vec: np.ndarray, courses: Sequence[UUID], n: int) -> list[dict]:
    return conn.execute(
        """
        SELECT f.id AS frame_id, f.lecture_id, f.t_s, 1 - (f.clip_emb <=> %(v)s) AS score
          FROM frames f JOIN lectures l ON l.id = f.lecture_id
         WHERE l.course_id = ANY(%(courses)s) AND f.clip_emb IS NOT NULL
         ORDER BY f.clip_emb <=> %(v)s LIMIT %(n)s
        """,
        {"v": vec, "courses": list(courses), "n": n},
    ).fetchall()


def _frames_to_segments(conn, rows: list[dict]) -> list[dict]:
    """Attach each frame hit to the window that starts closest before it."""
    if not rows:
        return []
    mapped = conn.execute(
        """
        SELECT h.ord, s.id AS segment_id, s.lecture_id, s.start_s, s.end_s
          FROM unnest(%s::uuid[], %s::float8[], %s::int[]) AS h(lecture_id, t_s, ord)
          CROSS JOIN LATERAL (
              SELECT id, lecture_id, start_s, end_s FROM segments
               WHERE lecture_id = h.lecture_id AND start_s <= h.t_s + 5
               ORDER BY start_s DESC LIMIT 1
          ) s
        """,
        (
            [r["lecture_id"] for r in rows],
            [r["t_s"] for r in rows],
            list(range(len(rows))),
        ),
    ).fetchall()
    out = []
    for m in sorted(mapped, key=lambda m: m["ord"]):
        r = rows[m["ord"]]
        out.append({**m, "score": r["score"], "frame_id": r["frame_id"]})
    return out


def retrieve(
    q: str, courses: Sequence[UUID], mode: str = "hybrid", n: int | None = None
) -> dict[int, Candidate]:
    """Run the retrievers for `mode` and collect candidates keyed by segment id."""
    from ..embed import clip_embedder, text_embedder

    n = n or get_settings().candidates
    used = MODES[mode]
    lists: dict[str, list[dict]] = {}
    with connection() as conn:
        conn.execute("SET hnsw.ef_search = 100")
        if "keyword" in used:
            lists["keyword"] = _keyword(conn, q, courses, n)
        if "meaning" in used:
            lists["meaning"] = _meaning(conn, text_embedder().embed([q])[0], courses, n)
        if "ocr" in used:
            lists["ocr"] = _frames_to_segments(conn, _ocr(conn, q, courses, n))
        if "visual" in used:
            vec = clip_embedder().embed_texts([q])[0]
            lists["visual"] = _frames_to_segments(conn, _visual(conn, vec, courses, n))

    cands: dict[int, Candidate] = {}
    for name, rows in lists.items():
        rank = 0
        for r in rows:
            c = cands.get(r["segment_id"])
            if c is None:
                c = cands[r["segment_id"]] = Candidate(
                    r["segment_id"], r["lecture_id"], r["start_s"], r["end_s"]
                )
            if name in c.ranks:  # two frames in one window: keep the better one
                continue
            rank += 1
            c.ranks[name] = rank
            c.scores[name] = float(r["score"])
            if r.get("frame_id") and c.frame_id is None:
                c.frame_id = r["frame_id"]
    return cands


def fuse(cands: dict[int, Candidate], k: int | None = None) -> list[tuple[Candidate, float]]:
    """RRF over the per-retriever rankings stored on the candidates."""
    k = k or get_settings().rrf_k
    names = sorted({n for c in cands.values() for n in c.ranks})
    rankings = [
        [
            sid
            for sid, _ in sorted(
                ((s, c.ranks[n]) for s, c in cands.items() if n in c.ranks), key=lambda x: x[1]
            )
        ]
        for n in names
    ]
    fused = rrf(rankings, k=k, weights=[WEIGHTS[n] for n in names])
    return [(cands[sid], score) for sid, score in fused]


def collapse(ranked: list[tuple[Candidate, float]], limit: int) -> list[tuple[Candidate, float]]:
    """Overlapping windows from the same minute become one result (the best one)."""
    hits = [(c.lecture_id, c.start_s, s) for c, s in ranked]
    return [ranked[g[0]] for g in group_by_time(hits)[:limit]]


def search(
    q: str, courses: Sequence[UUID], mode: str = "hybrid", limit: int = 10, tag: str | None = None
) -> list[Hit]:
    q = q.strip()
    if not q or not courses:
        return []
    ranked = fuse(retrieve(q, courses, mode))
    if tag:
        ranked = _with_tag(ranked, tag)
    return hydrate(q, collapse(ranked, limit))


def _with_tag(ranked: list[tuple[Candidate, float]], tag: str) -> list[tuple[Candidate, float]]:
    with connection() as conn:
        ok = {
            r["id"]
            for r in conn.execute(
                """
                SELECT s.id FROM segments s
                 WHERE s.id = ANY(%s) AND EXISTS (
                    SELECT 1 FROM frames f WHERE f.lecture_id = s.lecture_id
                       AND f.t_s BETWEEN s.start_s - 5 AND s.end_s AND f.tag = %s)
                """,
                ([c.segment_id for c, _ in ranked], tag),
            )
        }
    return [(c, s) for c, s in ranked if c.segment_id in ok]


def hydrate(q: str, ranked: list[tuple[Candidate, float]]) -> list[Hit]:
    """Fill in titles, the sentence to jump to, and the frame to show."""
    if not ranked:
        return []
    from ..embed import text_embedder

    qvec = text_embedder().embed([q])[0]
    ids = [c.segment_id for c, _ in ranked]
    with connection() as conn:
        segs = {
            r["id"]: r
            for r in conn.execute(
                """
                SELECT s.id, s.text, l.title, l.course_id, l.week
                  FROM segments s JOIN lectures l ON l.id = s.lecture_id WHERE s.id = ANY(%s)
                """,
                (ids,),
            )
        }
        out = []
        for c, score in ranked:
            # the sentence in this window closest in meaning to the query
            line = conn.execute(
                """
                SELECT start_s, text FROM transcript_lines
                 WHERE lecture_id = %s AND start_s < %s AND end_s > %s
                 ORDER BY CASE WHEN text_emb IS NULL THEN 2 ELSE text_emb <=> %s END, start_s
                 LIMIT 1
                """,
                (c.lecture_id, c.end_s, c.start_s, qvec),
            ).fetchone()
            frame = None
            if c.frame_id is not None:
                frame = conn.execute(
                    "SELECT t_s, thumb_key, tag, ocr_text FROM frames WHERE id = %s", (c.frame_id,)
                ).fetchone()
            if frame is None:
                # what was on screen when that sentence started
                at = line["start_s"] if line else c.start_s
                frame = conn.execute(
                    """
                    SELECT t_s, thumb_key, tag, ocr_text FROM frames
                     WHERE lecture_id = %s AND t_s <= %s + 2 ORDER BY t_s DESC LIMIT 1
                    """,
                    (c.lecture_id, at),
                ).fetchone()
            seg = segs[c.segment_id]
            out.append(
                Hit(
                    lecture_id=c.lecture_id,
                    lecture_title=seg["title"],
                    course_id=seg["course_id"],
                    week=seg["week"],
                    start_s=c.start_s,
                    end_s=c.end_s,
                    jump_s=line["start_s"] if line else c.start_s,
                    text=seg["text"],
                    sentence=line["text"] if line else "",
                    frame_t=frame["t_s"] if frame else None,
                    thumb_key=frame["thumb_key"] if frame else None,
                    tag=frame["tag"] if frame else None,
                    ocr_text=frame["ocr_text"] if frame else "",
                    score=score,
                    matched_by=sorted(c.ranks, key=lambda n: c.ranks[n]),
                    segment_id=c.segment_id,
                )
            )
    return out

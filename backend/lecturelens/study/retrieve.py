"""Find the parts of one lecture that matter for a question: keyword and meaning
matches over its 30s transcript windows, merged with reciprocal rank fusion."""

from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID

from ..search.fusion import rrf


@dataclass
class Excerpt:
    n: int  # 1-based, what citations refer to
    segment_id: int
    start_s: float
    end_s: float
    text: str
    keyword: bool  # has at least half the words of the question
    similarity: float | None  # cosine to the question, when the embedder is available


@lru_cache(maxsize=1)
def _embedder():
    try:
        from ..embed import text_embedder

        return text_embedder()
    except Exception:  # models not downloaded (unit tests, CI without the release)
        return None


def retrieve(conn, lecture_id: UUID, question: str, k: int = 6) -> list[Excerpt]:
    # any of the question's words, ranked by how many of them a window has
    kw = conn.execute(
        """
        WITH q AS (SELECT coalesce(array_agg(lexeme), '{}') AS lx
                     FROM unnest(to_tsvector('english', %(q)s)))
        SELECT s.id, cardinality(q.lx) AS n,
               (SELECT count(*) FROM unnest(q.lx) w WHERE s.tsv @@ plainto_tsquery('simple', w))
                 AS hits
          FROM segments s, q
         WHERE s.lecture_id = %(l)s AND cardinality(q.lx) > 0
           AND s.tsv @@ to_tsquery('simple', array_to_string(q.lx, ' | '))
         ORDER BY hits DESC, s.start_s LIMIT 20
        """,
        {"l": lecture_id, "q": question},
    ).fetchall()
    # on topic if it has at least half the question's words
    on_topic = {r["id"] for r in kw if 2 * r["hits"] >= r["n"]}
    lists = [[r["id"] for r in kw]]
    sims: dict[int, float] = {}
    emb = _embedder()
    if emb is not None:
        vec = emb.embed([question])[0]
        rows = conn.execute(
            """
            SELECT id, 1 - (text_emb <=> %(v)s) AS sim FROM segments
             WHERE lecture_id = %(l)s AND text_emb IS NOT NULL
             ORDER BY text_emb <=> %(v)s LIMIT 20
            """,
            {"l": lecture_id, "v": vec},
        ).fetchall()
        sims = {r["id"]: r["sim"] for r in rows}
        lists.append([r["id"] for r in rows])

    ranked = [sid for sid, _ in rrf(lists)][:k]
    if not ranked:
        return []
    rows = conn.execute(
        "SELECT id, start_s, end_s, text FROM segments WHERE id = ANY(%s)", (ranked,)
    ).fetchall()
    by_id = {r["id"]: r for r in rows}
    # number them in time order so the model (and the reader) see the lecture's flow
    chosen = sorted((by_id[s] for s in ranked), key=lambda r: r["start_s"])
    return [
        Excerpt(
            i + 1,
            r["id"],
            r["start_s"],
            r["end_s"],
            r["text"],
            r["id"] in on_topic,
            sims.get(r["id"]),
        )
        for i, r in enumerate(chosen)
    ]

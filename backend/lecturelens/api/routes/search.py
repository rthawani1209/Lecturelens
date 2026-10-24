from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ...db import connection
from ...search.engine import search

router = APIRouter(tags=["search"])


class HitOut(BaseModel):
    lecture_id: UUID
    lecture_title: str
    week: int | None
    start_s: float
    end_s: float
    jump_s: float
    sentence: str
    text: str
    frame_t: float | None
    thumb_url: str | None
    tag: str | None
    ocr_text: str
    score: float
    matched_by: list[str]


class SearchOut(BaseModel):
    query: str
    mode: str
    hits: list[HitOut]


@router.get("/search", response_model=SearchOut)
def search_lectures(
    q: str = Query(..., min_length=1, max_length=300),
    course: UUID | None = None,
    mode: Literal["hybrid", "text", "visual", "keyword", "meaning"] = "hybrid",
    tag: Literal["slide", "code", "whiteboard", "diagram", "professor"] | None = None,
    limit: int = Query(10, ge=1, le=50),
) -> dict:
    with connection() as conn:
        # until accounts land, search covers the public (openly licensed) courses
        rows = conn.execute(
            "SELECT id FROM courses WHERE public AND (%(c)s::uuid IS NULL OR id = %(c)s)",
            {"c": course},
        ).fetchall()
    courses = [r["id"] for r in rows]
    if course and not courses:
        raise HTTPException(404, "course not found")
    hits = search(q, courses, mode=mode, limit=limit, tag=tag)
    return {
        "query": q,
        "mode": mode,
        "hits": [
            {**h.__dict__, "thumb_url": f"/media/{h.thumb_key}" if h.thumb_key else None}
            for h in hits
        ],
    }

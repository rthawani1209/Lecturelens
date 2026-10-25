from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ... import access
from ...db import connection
from ...search.engine import search
from ..deps import current_user

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
    user: dict | None = Depends(current_user),
) -> dict:
    # only ever search courses this user can read
    with connection() as conn:
        courses = access.readable_courses(conn, user["id"] if user else None, course)
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

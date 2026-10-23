from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...db import connection

router = APIRouter(prefix="/courses", tags=["courses"])


class CourseOut(BaseModel):
    id: UUID
    code: str
    title: str
    term: str
    license: str
    lecture_count: int


class LectureOut(BaseModel):
    id: UUID
    title: str
    week: int | None
    duration_s: float | None
    status: str


# Only public (openly licensed) courses for now. Private courses arrive with auth.
@router.get("/public", response_model=list[CourseOut])
def list_public_courses() -> list[dict]:
    with connection() as conn:
        return conn.execute(
            """
            SELECT c.id, c.code, c.title, c.term, c.license, count(l.id) AS lecture_count
            FROM courses c LEFT JOIN lectures l ON l.course_id = c.id
            WHERE c.public
            GROUP BY c.id
            ORDER BY c.code
            """
        ).fetchall()


@router.get("/{course_id}/lectures", response_model=list[LectureOut])
def list_lectures(course_id: UUID) -> list[dict]:
    with connection() as conn:
        course = conn.execute("SELECT public FROM courses WHERE id = %s", (course_id,)).fetchone()
        # same 404 for "missing" and "not yours" so ids can't be probed
        if course is None or not course["public"]:
            raise HTTPException(404, "course not found")
        return conn.execute(
            "SELECT id, title, week, duration_s, status FROM lectures"
            " WHERE course_id = %s ORDER BY position",
            (course_id,),
        ).fetchall()

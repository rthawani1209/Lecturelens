from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ... import access
from ...db import connection
from ..deps import current_user, require_user

router = APIRouter(prefix="/courses", tags=["courses"])


class CourseOut(BaseModel):
    id: UUID
    code: str
    title: str
    term: str
    license: str
    public: bool
    mine: bool
    lecture_count: int


class CourseIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)  # "   " is empty

    title: str = Field(min_length=1, max_length=200)
    code: str = Field("", max_length=40)
    term: str = Field("", max_length=40)
    group_id: UUID | None = None
    # words the transcriber should spell right, e.g. "Dijkstra"
    terms: list[str] = Field(default_factory=list, max_length=200)


class LectureOut(BaseModel):
    id: UUID
    title: str
    week: int | None
    position: int
    duration_s: float | None
    status: str


class WeekOut(BaseModel):
    week: int | None  # None = lectures nobody has put in a week yet
    lectures: list[LectureOut]


_LIST = """
    SELECT c.id, c.code, c.title, c.term, c.license, c.public,
           EXISTS (SELECT 1 FROM group_members m
                    WHERE m.group_id = c.group_id AND m.user_id = %(u)s) AS mine,
           (SELECT count(*) FROM lectures l WHERE l.course_id = c.id) AS lecture_count
      FROM courses c WHERE c.id = ANY(%(ids)s) ORDER BY c.public, c.code, c.title
"""


@router.get("/public", response_model=list[CourseOut])
def list_public_courses() -> list[dict]:
    with connection() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM courses WHERE public")]
        return conn.execute(_LIST, {"u": None, "ids": ids}).fetchall()


@router.get("", response_model=list[CourseOut])
def list_courses(user: dict | None = Depends(current_user)) -> list[dict]:
    """Your courses first, then the public ones."""
    uid = user["id"] if user else None
    with connection() as conn:
        ids = access.readable_courses(conn, uid)
        return conn.execute(_LIST, {"u": uid, "ids": ids}).fetchall()


@router.post("", response_model=CourseOut, status_code=201)
def create_course(body: CourseIn, user: dict = Depends(require_user)) -> dict:
    with connection() as conn, conn.transaction():
        gid = access.writable_group(conn, user["id"], body.group_id)
        if gid is None:
            raise HTTPException(404, "group not found")
        cid = conn.execute(
            "INSERT INTO courses (group_id, code, title, term) VALUES (%s, %s, %s, %s)"
            " RETURNING id",
            (gid, body.code.strip(), body.title.strip(), body.term.strip()),
        ).fetchone()["id"]
        terms = {t.strip() for t in body.terms if t.strip()}
        if terms:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO course_terms (course_id, term) VALUES (%s, %s)",
                    [(cid, t[:80]) for t in sorted(terms)],
                )
        return conn.execute(_LIST, {"u": user["id"], "ids": [cid]}).fetchone()


@router.get("/{course_id}/lectures", response_model=list[LectureOut])
def list_lectures(course_id: UUID, user: dict | None = Depends(current_user)) -> list[dict]:
    with connection() as conn:
        # same 404 for "missing" and "not yours" so ids can't be probed
        if access.course(conn, user["id"] if user else None, course_id) is None:
            raise HTTPException(404, "course not found")
        return _lectures(conn, course_id)


@router.get("/{course_id}/weeks", response_model=list[WeekOut])
def list_weeks(course_id: UUID, user: dict | None = Depends(current_user)) -> list[dict]:
    with connection() as conn:
        if access.course(conn, user["id"] if user else None, course_id) is None:
            raise HTTPException(404, "course not found")
        lectures = _lectures(conn, course_id)
    weeks: dict[int | None, list[dict]] = {}
    for lec in lectures:
        weeks.setdefault(lec["week"], []).append(lec)
    # numbered weeks in order, then the unsorted ones
    order = sorted(w for w in weeks if w is not None) + ([None] if None in weeks else [])
    return [{"week": w, "lectures": weeks[w]} for w in order]


def _lectures(conn, course_id: UUID) -> list[dict]:
    return conn.execute(
        "SELECT id, title, week, position, duration_s, status FROM lectures"
        " WHERE course_id = %s ORDER BY position, created_at",
        (course_id,),
    ).fetchall()

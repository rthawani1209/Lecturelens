from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from ... import access
from ...db import connection
from ...storage import get_storage
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
    ready_count: int


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
           (SELECT count(*) FROM lectures l WHERE l.course_id = c.id) AS lecture_count,
           (SELECT count(*) FROM lectures l
             WHERE l.course_id = c.id AND l.status = 'ready') AS ready_count
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


class CourseEdit(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(None, min_length=1, max_length=200)
    code: str | None = Field(None, max_length=40)


def _own(conn, user: dict, course_id: UUID) -> dict:
    course = access.course(conn, user["id"], course_id, write=True)
    if course is None:
        raise HTTPException(404, "course not found")
    return course


@router.patch("/{course_id}", response_model=CourseOut)
def edit_course(course_id: UUID, body: CourseEdit, user: dict = Depends(require_user)) -> dict:
    with connection() as conn:
        _own(conn, user, course_id)
        conn.execute(
            "UPDATE courses SET title = coalesce(%s, title), code = coalesce(%s, code)"
            " WHERE id = %s",
            (body.title, body.code, course_id),
        )
        return conn.execute(_LIST, {"u": user["id"], "ids": [course_id]}).fetchone()


@router.delete("/{course_id}", status_code=204)
def delete_course(course_id: UUID, user: dict = Depends(require_user)) -> Response:
    """The course, its lectures and every file they stored."""
    from . import uploads as uploads_routes

    with connection() as conn:
        _own(conn, user, course_id)
        lectures = conn.execute(
            "SELECT id FROM lectures WHERE course_id = %s", (course_id,)
        ).fetchall()
        parts = conn.execute(
            "SELECT u.id FROM uploads u JOIN lectures l ON l.id = u.lecture_id"
            " WHERE l.course_id = %s",
            (course_id,),
        ).fetchall()
        conn.execute("DELETE FROM courses WHERE id = %s", (course_id,))
    # files after the rows, so a half-finished delete never leaves rows pointing at nothing
    storage = get_storage()
    for lec in lectures:
        storage.delete_prefix(f"lectures/{lec['id']}/")
    for up in parts:
        uploads_routes.part_path(up["id"]).unlink(missing_ok=True)
    return Response(status_code=204)


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

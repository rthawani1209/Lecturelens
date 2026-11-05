"""Everything the Watch screen needs in one call, plus the viewer's own notes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from ... import access
from ...db import connection
from ..deps import current_user, require_user
from .media import media_url

router = APIRouter(tags=["watch"])


class CourseRef(BaseModel):
    id: UUID
    code: str
    title: str


class LineOut(BaseModel):
    start_s: float
    end_s: float
    text: str


class FrameOut(BaseModel):
    t_s: float
    tag: str | None
    thumb_url: str | None


class WatchOut(BaseModel):
    id: UUID
    title: str
    week: int | None
    position: int
    duration_s: float | None
    status: str
    course: CourseRef
    video_url: str | None
    transcript: list[LineOut]
    frames: list[FrameOut]


class NoteIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)  # "   " is empty

    t_s: float = Field(ge=0, le=48 * 3600, allow_inf_nan=False)
    text: str = Field(min_length=1, max_length=2000)


class NoteOut(BaseModel):
    id: UUID
    t_s: float
    text: str


def _lecture_or_404(conn, lecture_id: UUID, user: dict | None) -> dict:
    lec = access.lecture(conn, user["id"] if user else None, lecture_id)
    if lec is None:
        raise HTTPException(404, "lecture not found")
    return lec


@router.get("/lectures/{lecture_id}/watch", response_model=WatchOut)
def watch(lecture_id: UUID, user: dict | None = Depends(current_user)) -> dict:
    with connection() as conn:
        _lecture_or_404(conn, lecture_id, user)
        lec = conn.execute(
            """
            SELECT l.id, l.title, l.week, l.position, l.duration_s, l.status, l.storage_key,
                   c.id AS course_id, c.code, c.title AS course_title
              FROM lectures l JOIN courses c ON c.id = l.course_id WHERE l.id = %s
            """,
            (lecture_id,),
        ).fetchone()
        lines = conn.execute(
            "SELECT start_s, end_s, text FROM transcript_lines"
            " WHERE lecture_id = %s ORDER BY start_s",
            (lecture_id,),
        ).fetchall()
        frames = conn.execute(
            "SELECT t_s, tag, thumb_key FROM frames WHERE lecture_id = %s ORDER BY t_s",
            (lecture_id,),
        ).fetchall()
    return {
        **lec,
        "course": {"id": lec["course_id"], "code": lec["code"], "title": lec["course_title"]},
        "video_url": media_url(lec["storage_key"]) if lec["status"] == "ready" else None,
        "transcript": lines,
        "frames": [
            {"t_s": f["t_s"], "tag": f["tag"], "thumb_url": media_url(f["thumb_key"])}
            for f in frames
        ],
    }


@router.get("/lectures/{lecture_id}/notes", response_model=list[NoteOut])
def list_notes(lecture_id: UUID, user: dict = Depends(require_user)) -> list[dict]:
    with connection() as conn:
        _lecture_or_404(conn, lecture_id, user)
        return conn.execute(
            "SELECT id, start_s AS t_s, note AS text FROM highlights"
            " WHERE user_id = %s AND lecture_id = %s ORDER BY start_s, created_at",
            (user["id"], lecture_id),
        ).fetchall()


@router.post("/lectures/{lecture_id}/notes", response_model=NoteOut, status_code=201)
def add_note(lecture_id: UUID, body: NoteIn, user: dict = Depends(require_user)) -> dict:
    with connection() as conn:
        _lecture_or_404(conn, lecture_id, user)
        return conn.execute(
            "INSERT INTO highlights (user_id, lecture_id, start_s, end_s, note)"
            " VALUES (%s, %s, %s, %s, %s) RETURNING id, start_s AS t_s, note AS text",
            (user["id"], lecture_id, body.t_s, body.t_s, body.text.strip()),
        ).fetchone()


@router.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: UUID, user: dict = Depends(require_user)) -> Response:
    with connection() as conn:
        gone = conn.execute(
            "DELETE FROM highlights WHERE id = %s AND user_id = %s", (note_id, user["id"])
        ).rowcount
    if not gone:
        raise HTTPException(404, "note not found")
    return Response(status_code=204)

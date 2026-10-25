import json
import time
from collections.abc import Iterator
from pathlib import PurePosixPath
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ... import access, queue, signing
from ...config import get_settings
from ...db import connection
from ...pipeline.fetch import canonical_url, youtube_id
from ...pipeline.stages import STAGES
from ..deps import current_user, require_user

router = APIRouter(tags=["lectures"])

VIDEO_TYPES = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
UPLOAD_URL_TTL_S = 24 * 3600


class UploadIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0)
    week: int | None = Field(None, ge=0, le=52)


class UploadOut(BaseModel):
    lecture_id: UUID
    upload_url: str
    chunk_size: int


class ImportIn(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    title: str = Field("", max_length=200)
    week: int | None = Field(None, ge=0, le=52)


class StageOut(BaseModel):
    stage: str
    status: str
    progress: float
    error: str | None = None


class LectureDetail(BaseModel):
    id: UUID
    course_id: UUID
    title: str
    week: int | None
    duration_s: float | None
    status: str
    source_url: str | None
    progress: float
    stages: list[StageOut]


def upload_url(upload_id: UUID) -> str:
    exp, sig = signing.sign(str(upload_id), UPLOAD_URL_TTL_S)
    return f"/uploads/{upload_id}?exp={exp}&sig={sig}"


def _next_position(conn, course_id: UUID) -> int:
    return conn.execute(
        "SELECT coalesce(max(position), 0) + 1 AS p FROM lectures WHERE course_id = %s",
        (course_id,),
    ).fetchone()["p"]


@router.post("/courses/{course_id}/lectures", response_model=UploadOut, status_code=201)
def start_upload(course_id: UUID, body: UploadIn, user: dict = Depends(require_user)) -> dict:
    """Create the lecture and hand back a signed URL to send the file to in chunks."""
    s = get_settings()
    ext = PurePosixPath(body.filename).suffix.lower()
    if ext not in VIDEO_TYPES:
        raise HTTPException(415, f"upload a video file ({', '.join(sorted(VIDEO_TYPES))})")
    if body.size > s.max_upload_bytes:
        raise HTTPException(413, "file is too large")
    with connection() as conn, conn.transaction():
        if access.course(conn, user["id"], course_id, write=True) is None:
            raise HTTPException(404, "course not found")
        lid = conn.execute(
            "INSERT INTO lectures (course_id, title, week, position, status, created_by)"
            " VALUES (%s, %s, %s, %s, 'uploading', %s) RETURNING id",
            (course_id, body.title.strip(), body.week, _next_position(conn, course_id), user["id"]),
        ).fetchone()["id"]
        uid = conn.execute(
            "INSERT INTO uploads (lecture_id, user_id, filename, size) VALUES (%s, %s, %s, %s)"
            " RETURNING id",
            (lid, user["id"], body.filename, body.size),
        ).fetchone()["id"]
    return {"lecture_id": lid, "upload_url": upload_url(uid), "chunk_size": s.upload_chunk_bytes}


@router.post("/courses/{course_id}/lectures/import", response_model=LectureDetail, status_code=201)
def import_lecture(course_id: UUID, body: ImportIn, user: dict = Depends(require_user)) -> dict:
    vid = youtube_id(body.url)
    if vid is None:
        raise HTTPException(422, "paste a YouTube video link")
    with connection() as conn, conn.transaction():
        if access.course(conn, user["id"], course_id, write=True) is None:
            raise HTTPException(404, "course not found")
        # empty title: the fetch stage fills in the video's own title
        lid = conn.execute(
            "INSERT INTO lectures (course_id, title, week, position, status, source_url,"
            " created_by) VALUES (%s, %s, %s, %s, 'queued', %s, %s) RETURNING id",
            (
                course_id,
                body.title.strip(),
                body.week,
                _next_position(conn, course_id),
                canonical_url(vid),
                user["id"],
            ),
        ).fetchone()["id"]
    queue.enqueue(lid)
    return _detail(lid)


def _detail(lecture_id: UUID) -> dict:
    with connection() as conn:
        lec = conn.execute(
            "SELECT id, course_id, title, week, duration_s, status, source_url FROM lectures"
            " WHERE id = %s",
            (lecture_id,),
        ).fetchone()
        rows = {
            r["stage"]: r
            for r in conn.execute(
                "SELECT stage, status, progress, error FROM jobs WHERE lecture_id = %s",
                (lecture_id,),
            )
        }
    stages = []
    for name, _ in STAGES:
        r = rows.get(name)
        stages.append(
            {
                "stage": name,
                "status": r["status"] if r else "pending",
                "progress": r["progress"] if r else 0.0,
                # first line only; tracebacks stay in the logs
                "error": r["error"].splitlines()[0] if r and r["error"] else None,
            }
        )
    progress = 1.0 if lec["status"] == "ready" else sum(s["progress"] for s in stages) / len(STAGES)
    return {**lec, "stages": stages, "progress": round(progress, 3)}


def _readable(lecture_id: UUID, user: dict | None) -> None:
    with connection() as conn:
        if access.lecture(conn, user["id"] if user else None, lecture_id) is None:
            raise HTTPException(404, "lecture not found")


@router.get("/lectures/{lecture_id}", response_model=LectureDetail)
def get_lecture(lecture_id: UUID, user: dict | None = Depends(current_user)) -> dict:
    _readable(lecture_id, user)
    return _detail(lecture_id)


@router.get("/lectures/{lecture_id}/events")
def lecture_events(
    lecture_id: UUID, user: dict | None = Depends(current_user)
) -> StreamingResponse:
    """Server-sent events with pipeline progress, so the upload page can show it live."""
    _readable(lecture_id, user)
    return StreamingResponse(
        progress_events(lecture_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def progress_events(
    lecture_id: UUID, poll_s: float = 1.0, ping_s: float = 15.0, max_s: float = 4 * 3600
) -> Iterator[str]:
    last, last_sent, started = None, time.monotonic(), time.monotonic()
    while time.monotonic() - started < max_s:
        detail = _detail(lecture_id)
        snapshot = json.dumps(detail, default=str)
        if snapshot != last:
            yield f"event: progress\ndata: {snapshot}\n\n"
            last, last_sent = snapshot, time.monotonic()
        elif time.monotonic() - last_sent > ping_s:
            yield ": ping\n\n"  # keeps proxies from closing an idle stream
            last_sent = time.monotonic()
        if detail["status"] in ("ready", "failed"):
            return
        time.sleep(poll_s)

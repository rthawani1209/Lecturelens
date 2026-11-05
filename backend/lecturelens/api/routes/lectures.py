import asyncio
import json
import time
from collections.abc import AsyncIterator
from pathlib import PurePosixPath
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from ... import access, queue, signing
from ...config import get_settings
from ...db import connection
from ...pipeline.fetch import canonical_url, youtube_id
from ...pipeline.stages import STAGES
from ...storage import get_storage
from ..deps import current_user, require_user
from . import uploads as uploads_routes

router = APIRouter(tags=["lectures"])

VIDEO_TYPES = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
UPLOAD_URL_TTL_S = 24 * 3600


class UploadIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)  # "   " is empty

    title: str = Field(min_length=1, max_length=200)
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0)
    week: int | None = Field(None, ge=0, le=52)


class UploadOut(BaseModel):
    lecture_id: UUID
    upload_url: str
    chunk_size: int


class ImportIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)  # "   " is empty

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


def _size(n: int) -> str:
    return f"{n / 1024**3:g} GB" if n >= 1024**3 else f"{n / 1024**2:g} MB"


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
        kinds = ", ".join(t.lstrip(".") for t in sorted(VIDEO_TYPES))
        raise HTTPException(415, f"That isn't a video file. Upload one of: {kinds}.")
    if body.size > s.max_upload_bytes:
        raise HTTPException(413, f"This file is too big. The limit is {_size(s.max_upload_bytes)}.")
    with connection() as conn, conn.transaction():
        if access.course(conn, user["id"], course_id, write=True) is None:
            raise HTTPException(404, "course not found")
        _daily_limit(conn, user["id"])
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
    uploads_routes.sweep_parts(UPLOAD_URL_TTL_S)
    return {"lecture_id": lid, "upload_url": upload_url(uid), "chunk_size": s.upload_chunk_bytes}


@router.post("/courses/{course_id}/lectures/import", response_model=LectureDetail, status_code=201)
def import_lecture(course_id: UUID, body: ImportIn, user: dict = Depends(require_user)) -> dict:
    vid = youtube_id(body.url)
    if vid is None:
        raise HTTPException(422, "paste a YouTube video link")
    with connection() as conn, conn.transaction():
        if access.course(conn, user["id"], course_id, write=True) is None:
            raise HTTPException(404, "course not found")
        _daily_limit(conn, user["id"])
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


def _daily_limit(conn, user_id) -> None:
    """Count this addition against today's caps, or refuse it with a 429.

    Runs inside the caller's transaction. The advisory lock makes concurrent
    requests take turns, so twelve at once can't all see "4 so far".
    """
    s = get_settings()
    if not (s.daily_lectures_per_user or s.daily_lectures_total):
        return
    conn.execute("SELECT pg_advisory_xact_lock(hashtext('lecture_adds'))")
    if s.daily_lectures_per_user:
        n = conn.execute(
            "SELECT count(*) AS n FROM lecture_adds"
            " WHERE user_id = %s AND at > now() - interval '1 day'",
            (user_id,),
        ).fetchone()["n"]
        if n >= s.daily_lectures_per_user:
            raise HTTPException(
                429,
                f"You've added {n} lectures today, the most this site allows. Try again tomorrow.",
            )
    if s.daily_lectures_total:
        n = conn.execute(
            "SELECT count(*) AS n FROM lecture_adds WHERE at > now() - interval '1 day'"
        ).fetchone()["n"]
        if n >= s.daily_lectures_total:
            raise HTTPException(
                429, "This demo has processed all the uploads it can for today. Try again tomorrow."
            )
    conn.execute("INSERT INTO lecture_adds (user_id) VALUES (%s)", (user_id,))


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
                # plain words for people; the full error stays in jobs.error and the logs
                "error": friendly_error(name, r["error"]) if r and r["error"] else None,
            }
        )
    progress = 1.0 if lec["status"] == "ready" else sum(s["progress"] for s in stages) / len(STAGES)
    return {**lec, "stages": stages, "progress": round(progress, 3)}


def friendly_error(stage: str, error: str) -> str:
    if error.startswith("MediaError"):
        if stage == "fetch":
            return "Couldn't download this video. Check the link and that it's public."
        if "no video track" in error:
            return "This file has sound but no picture. Upload the video itself."
        if "convert it to MP4" in error:
            return "Browsers can't play this format. Convert it to MP4 (H.264) and upload again."
        return "This file isn't a playable video."
    return f"Something went wrong while processing ({stage}). Try again."


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
        # no-transform: proxies (including the web app's /api rewrite) must not gzip
        # and buffer the stream, or progress only shows up when it ends
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


async def progress_events(
    lecture_id: UUID, poll_s: float = 1.0, ping_s: float = 15.0, max_s: float = 4 * 3600
) -> AsyncIterator[str]:
    # async so an open stream holds no worker thread while it waits; only the
    # database read borrows one, for a moment
    last, last_sent, started = None, time.monotonic(), time.monotonic()
    while time.monotonic() - started < max_s:
        detail = await asyncio.to_thread(_detail, lecture_id)
        snapshot = json.dumps(detail, default=str)
        if snapshot != last:
            yield f"event: progress\ndata: {snapshot}\n\n"
            last, last_sent = snapshot, time.monotonic()
        elif time.monotonic() - last_sent > ping_s:
            yield ": ping\n\n"  # keeps proxies from closing an idle stream
            last_sent = time.monotonic()
        if detail["status"] in ("ready", "failed"):
            return
        # nothing changes server-side while the browser is still sending the file
        await asyncio.sleep(poll_s * 5 if detail["status"] == "uploading" else poll_s)


def _writable(lecture_id: UUID, user: dict) -> dict:
    with connection() as conn:
        lec = access.lecture(conn, user["id"], lecture_id, write=True)
    if lec is None:
        raise HTTPException(404, "lecture not found")
    return lec


@router.post("/lectures/{lecture_id}/retry", response_model=LectureDetail)
def retry_lecture(lecture_id: UUID, user: dict = Depends(require_user)) -> dict:
    """Run a failed lecture again. Stages that finished are skipped."""
    lec = _writable(lecture_id, user)
    if lec["status"] != "failed":
        raise HTTPException(409, "only failed lectures can be retried")
    with connection() as conn:
        conn.execute(
            "UPDATE jobs SET status = 'pending', error = NULL, progress = 0"
            " WHERE lecture_id = %s AND status = 'failed'",
            (lecture_id,),
        )
        conn.execute("UPDATE lectures SET status = 'queued' WHERE id = %s", (lecture_id,))
    queue.enqueue(lecture_id)
    return _detail(lecture_id)


@router.delete("/lectures/{lecture_id}", status_code=204)
def delete_lecture(lecture_id: UUID, user: dict = Depends(require_user)) -> Response:
    lec = _writable(lecture_id, user)
    storage = get_storage()
    storage.delete_prefix(f"lectures/{lecture_id}")
    # uploaded sources live under lectures/<id>/ too; demo sources are shared, keep them
    if lec["storage_key"] and lec["storage_key"].startswith(f"lectures/{lecture_id}/"):
        storage.delete_prefix(lec["storage_key"])
    with connection() as conn:
        uploads = conn.execute(
            "DELETE FROM uploads WHERE lecture_id = %s RETURNING id", (lecture_id,)
        ).fetchall()
        conn.execute("DELETE FROM lectures WHERE id = %s", (lecture_id,))
    for up in uploads:  # a half-sent file would otherwise sit on disk forever
        uploads_routes.part_path(up["id"]).unlink(missing_ok=True)
    return Response(status_code=204)

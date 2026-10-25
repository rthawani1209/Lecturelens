"""Resumable uploads, using the same protocol as Google Cloud Storage resumable uploads:

  PUT <upload_url>  Content-Range: bytes 0-8388607/52428800   (a chunk)
  PUT <upload_url>  Content-Range: bytes */52428800            (how much do you have?)

Unfinished chunks get 308 with `Range: bytes=0-<last byte stored>`, so a client that
lost its connection asks where to resume and carries on from there. The URL is
signed, so chunks don't need the session cookie and the link can't be guessed.
"""

import re
from pathlib import Path, PurePosixPath
from uuid import UUID

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response

from ... import queue, signing
from ...config import get_settings
from ...db import connection
from ...storage import get_storage

router = APIRouter(tags=["uploads"])

_RANGE = re.compile(r"^bytes (?:(\d+)-(\d+)|\*)/(\d+)$")
MAX_CHUNK = 64 * 1024**2


def _resume(received: int) -> Response:
    headers = {"Range": f"bytes=0-{received - 1}"} if received else {}
    return Response(status_code=308, headers=headers)


def _part(upload_id: UUID) -> Path:
    return Path(get_settings().upload_dir) / f"{upload_id}.part"


@router.put("/uploads/{upload_id}")
async def put_chunk(upload_id: UUID, request: Request, exp: int = 0, sig: str = "") -> Response:
    if not signing.verify(str(upload_id), exp, sig):
        raise HTTPException(403, "upload link is invalid or has expired")
    m = _RANGE.match(request.headers.get("content-range", ""))
    if not m:
        raise HTTPException(400, "send a Content-Range header")
    first, last, total = (int(g) if g is not None else None for g in m.groups())

    body = bytearray()
    if first is not None:
        if last < first or last - first + 1 > MAX_CHUNK:
            raise HTTPException(400, "bad chunk range")
        async for piece in request.stream():
            body += piece
            if len(body) > last - first + 1:
                raise HTTPException(400, "chunk is longer than its Content-Range")
        if len(body) != last - first + 1:
            raise HTTPException(400, "chunk is shorter than its Content-Range")
    return _store(upload_id, first, total, bytes(body))


def _store(upload_id: UUID, first: int | None, total: int, body: bytes) -> Response:
    with connection() as conn, conn.transaction():
        try:
            up = conn.execute(
                "SELECT * FROM uploads WHERE id = %s FOR UPDATE NOWAIT", (upload_id,)
            ).fetchone()
        except psycopg.errors.LockNotAvailable:
            raise HTTPException(409, "another chunk for this upload is in flight") from None
        if up is None:
            raise HTTPException(404)
        if up["done"]:
            return Response(status_code=200)
        if total != up["size"]:
            raise HTTPException(400, "total size doesn't match the upload")
        # a status check, or a chunk that isn't the next one: tell the client where we are
        if first is None or first != up["received"]:
            return _resume(up["received"])

        part = _part(upload_id)
        part.parent.mkdir(parents=True, exist_ok=True)
        with open(part, "r+b" if part.exists() else "wb") as f:
            f.seek(first)
            f.write(body)
            f.truncate()
        received = first + len(body)
        conn.execute("UPDATE uploads SET received = %s WHERE id = %s", (received, upload_id))
        if received < up["size"]:
            return _resume(received)

        ext = PurePosixPath(up["filename"]).suffix.lower()
        key = f"lectures/{up['lecture_id']}/source{ext}"
        get_storage().put_file(key, part)
        conn.execute("UPDATE uploads SET done = true WHERE id = %s", (upload_id,))
        conn.execute(
            "UPDATE lectures SET storage_key = %s, status = 'queued' WHERE id = %s",
            (key, up["lecture_id"]),
        )
    part.unlink(missing_ok=True)
    queue.enqueue(up["lecture_id"])
    return Response(status_code=201)

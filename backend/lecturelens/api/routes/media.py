import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ... import access
from ...db import connection
from ...storage import get_storage
from ..deps import current_user

router = APIRouter(tags=["media"])


@router.get("/media/lectures/{lecture_id}/frames/{name}")
def frame_image(
    lecture_id: UUID, name: str, user: dict | None = Depends(current_user)
) -> FileResponse:
    if not name.endswith(".jpg") or "/" in name or name.startswith("."):
        raise HTTPException(404)
    with connection() as conn:
        lec = access.lecture(conn, user["id"] if user else None, lecture_id)
    key = f"lectures/{lecture_id}/frames/{name}"
    storage = get_storage()
    if lec is None or not storage.exists(key):
        raise HTTPException(404)
    dst = Path(tempfile.gettempdir()) / "ll-media" / str(lecture_id) / name
    if not dst.exists():
        storage.get_file(key, dst)
    # private thumbnails must not sit in shared caches
    cache = "public, max-age=86400" if lec["public"] else "private, max-age=3600"
    return FileResponse(dst, media_type="image/jpeg", headers={"Cache-Control": cache})

import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ...db import connection
from ...storage import get_storage

router = APIRouter(tags=["media"])


# Thumbnails of public lectures. Private media will go through short-lived signed
# URLs instead, so this route never has to make an access decision for them.
@router.get("/media/lectures/{lecture_id}/frames/{name}")
def frame_image(lecture_id: UUID, name: str) -> FileResponse:
    if not name.endswith(".jpg") or "/" in name or name.startswith("."):
        raise HTTPException(404)
    with connection() as conn:
        ok = conn.execute(
            "SELECT 1 FROM lectures l JOIN courses c ON c.id = l.course_id"
            " WHERE l.id = %s AND c.public",
            (lecture_id,),
        ).fetchone()
    key = f"lectures/{lecture_id}/frames/{name}"
    storage = get_storage()
    if not ok or not storage.exists(key):
        raise HTTPException(404)
    dst = Path(tempfile.gettempdir()) / "ll-media" / str(lecture_id) / name
    if not dst.exists():
        storage.get_file(key, dst)
    return FileResponse(
        dst, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"}
    )

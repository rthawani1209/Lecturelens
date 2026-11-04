"""Videos and thumbnails, served only through short-lived signed links.

The API checks who can see a lecture when it hands out a link (search, watch).
The link itself carries an HMAC and an expiry, so the media route needs no session
and works for <video> range requests and <img> tags alike.
"""

import mimetypes
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from ... import signing
from ...storage import LocalStorage, get_storage

router = APIRouter(tags=["media"])

MEDIA_TTL_S = 15 * 60
TYPES = {
    ".jpg": "image/jpeg",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
}


def media_url(key: str | None, ttl_s: int = MEDIA_TTL_S) -> str | None:
    if not key:
        return None
    exp, sig = signing.sign(f"media:{key}", ttl_s)
    return f"/media/{key}?exp={exp}&sig={sig}"


@router.get("/media/{key:path}")
def media(key: str, exp: int = Query(...), sig: str = Query(...)) -> FileResponse:
    if not signing.verify(f"media:{key}", exp, sig):
        raise HTTPException(403, "link expired or invalid")
    ext = Path(key).suffix.lower()
    if ext not in TYPES:
        raise HTTPException(404)
    storage = get_storage()
    try:
        if isinstance(storage, LocalStorage):
            path = storage.path(key)
        else:
            # S3/GCS: keep a local copy so range requests are cheap after the first
            path = Path(tempfile.gettempdir()) / "ll-media" / key
            if not path.exists():
                storage.get_file(key, path)
    except ValueError:
        raise HTTPException(404) from None
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(
        path,
        media_type=TYPES.get(ext) or mimetypes.guess_type(key)[0],
        # the link is a bearer token: keep it out of shared caches
        headers={"Cache-Control": f"private, max-age={MEDIA_TTL_S}"},
    )

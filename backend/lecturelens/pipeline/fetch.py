"""Pull a lecture in from YouTube instead of an upload."""

import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .media import MediaError

_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}


def youtube_id(url: str) -> str | None:
    """The video id from any of the usual YouTube link shapes, or None."""
    try:
        u = urlparse(url.strip())
    except ValueError:
        return None
    if u.scheme not in ("http", "https") or (u.hostname or "") not in _HOSTS:
        return None
    if u.hostname == "youtu.be":
        vid = u.path.lstrip("/").split("/")[0]
    elif u.path == "/watch":
        vid = parse_qs(u.query).get("v", [""])[0]
    else:
        parts = u.path.strip("/").split("/")
        vid = parts[1] if len(parts) >= 2 and parts[0] in ("shorts", "embed", "live") else ""
    return vid if _ID.match(vid) else None


def canonical_url(video_id: str) -> str:
    # we only ever hand yt-dlp a URL we built, never the one the user typed
    return f"https://www.youtube.com/watch?v={video_id}"


def download_youtube(url: str, out_dir: Path, max_bytes: int) -> tuple[Path, str]:
    """Download one video (720p is plenty for OCR). Returns (file, title)."""
    import yt_dlp

    opts = {
        "format": "best[height<=720][ext=mp4]/best[height<=720]/best",
        "outtmpl": str(out_dir / "source.%(ext)s"),
        "noplaylist": True,
        "max_filesize": max_bytes,
        "quiet": True,
        "no_warnings": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as e:
        raise MediaError(f"couldn't download the video: {e}") from e
    files = list(out_dir.glob("source.*"))
    if not files:
        raise MediaError("video was larger than the upload limit")
    return files[0], info.get("title") or ""

"""Download one real YouTube video the way the import does, and check it's usable.

The tests never touch YouTube (it's slow and flaky from CI), so this is run by hand
from the "YouTube import" workflow when yt-dlp or YouTube changes.
"""

import argparse
import sys
import tempfile
from pathlib import Path

from lecturelens.pipeline.fetch import canonical_url, download_youtube, youtube_id
from lecturelens.pipeline.media import looks_like_video, probe


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--max-mb", type=int, default=2048)
    args = ap.parse_args()

    vid = youtube_id(args.url)
    if not vid:
        print(f"not a YouTube link: {args.url}")
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        path, title = download_youtube(canonical_url(vid), Path(tmp), args.max_mb * 1024**2)
        head = path.read_bytes()[:64]
        info = probe(path)
        print(f"{title!r}: {path.name}, {path.stat().st_size / 1e6:.1f} MB, {info}")
        if not (looks_like_video(head) and info["has_video"] and info["has_audio"]):
            print("downloaded file isn't a usable lecture video")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

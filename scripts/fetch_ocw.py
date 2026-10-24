"""Download the lectures of an MIT OpenCourseWare course: video, captions and metadata.

OCW has no API, so this reads the course's lecture video gallery and follows each
lecture's resource page to its video file (hosted on archive.org) and caption file.
Falls back to the YouTube copy through yt-dlp when a page has no direct video link.

  python scripts/fetch_ocw.py --course 6-006-introduction-to-algorithms-spring-2020 \
      --out data/ocw/6.006 [--limit 3]

Content is (c) MIT, licensed CC BY-NC-SA 4.0. Keep the attribution in manifest.json.
"""

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

BASE = "https://ocw.mit.edu"
UA = "LectureLens dataset builder (github.com/rthawani1209/Lecturelens)"


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self._href, self._text = a["href"], []
        # captions and youtube ids sometimes only show up in data attributes
        for v in a.values():
            if v and ("youtube.com/embed/" in v or v.endswith((".vtt", ".srt"))):
                self.links.append((v, ""))

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._text).split())))
            self._href = None


def get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001 - retry anything network-ish
            if attempt == 3:
                raise
            print(f"  retry {url}: {e}", file=sys.stderr)
            time.sleep(2**attempt)
    raise AssertionError


def links(url: str) -> list[tuple[str, str]]:
    p = Links()
    p.feed(get(url))
    return [(urljoin(url, h), t) for h, t in p.links]


def download(url: str, dst: Path) -> None:
    if dst.exists() and dst.stat().st_size > 0:
        return
    tmp = dst.with_suffix(dst.suffix + ".part")
    subprocess.run(["curl", "-fsSL", "--retry", "5", "-A", UA, "-o", str(tmp), url], check=True)
    tmp.rename(dst)


def lecture_pages(course: str) -> list[tuple[str, str]]:
    root = f"{BASE}/courses/{course}/"
    for gallery in ("video_galleries/lecture-videos/", "pages/lecture-videos/"):
        try:
            found = [
                (u, t)
                for u, t in links(root + gallery)
                if f"/courses/{course}/resources/" in u and re.search(r"lecture-\d+", u)
            ]
        except Exception as e:  # noqa: BLE001
            print(f"no gallery at {gallery}: {e}", file=sys.stderr)
            continue
        if found:
            seen, out = set(), []
            for u, t in found:
                if u not in seen:
                    seen.add(u)
                    out.append((u, t))
            return out
    raise SystemExit(f"could not find lecture pages for {course}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--course", default="6-006-introduction-to-algorithms-spring-2020")
    ap.add_argument("--out", type=Path, default=Path("data/ocw/6.006"))
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    pages = lecture_pages(args.course)
    if args.limit:
        pages = pages[: args.limit]
    print(f"{len(pages)} lecture pages")

    lectures = []
    for page, title in pages:
        num = int(re.search(r"lecture-(\d+)", page).group(1))
        found = links(page)
        mp4 = next((u for u, _ in found if u.endswith(".mp4") and "archive.org" in u), None)
        mp4 = mp4 or next((u for u, _ in found if u.endswith(".mp4")), None)
        caps = next((u for u, _ in found if u.endswith((".vtt", ".srt"))), None)
        yt = next(
            (
                m.group(1)
                for u, _ in found
                if (m := re.search(r"youtube\.com/(?:embed/|watch\?v=)([\w-]{11})", u))
            ),
            None,
        )
        stem = f"lec{num:02d}"
        print(f"{stem}: mp4={mp4} captions={caps} youtube={yt}")

        video = args.out / f"{stem}.mp4"
        if mp4:
            download(mp4, video)
        elif yt:
            subprocess.run(
                [
                    "yt-dlp",
                    "-f",
                    "18/best[height<=480]",
                    "-o",
                    str(video),
                    f"https://www.youtube.com/watch?v={yt}",
                ],
                check=True,
            )
        else:
            print(f"  skipping {stem}: no video found", file=sys.stderr)
            continue
        cap_file = None
        if caps:
            cap_file = f"{stem}{Path(caps).suffix}"
            download(caps, args.out / cap_file)
        lectures.append(
            {
                "number": num,
                "title": title or stem,
                "page": page,
                "video": video.name,
                "captions": cap_file,
                "youtube_id": yt,
                "source_url": mp4,
            }
        )

    lectures.sort(key=lambda x: x["number"])
    manifest = {
        "course": args.course,
        "url": f"{BASE}/courses/{args.course}/",
        "license": "CC BY-NC-SA 4.0",
        "attribution": "MIT OpenCourseWare, https://ocw.mit.edu",
        "lectures": lectures,
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"wrote {len(lectures)} lectures to {args.out}")


if __name__ == "__main__":
    main()

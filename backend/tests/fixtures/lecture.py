"""Builds a short synthetic lecture with known answers.

Each "slide" is rendered with Pillow and narrated by espeak-ng, then ffmpeg
stitches them into one mp4. Because we wrote the script, we know exactly what
was said, what was on screen and when every slide starts, so pipeline tests can
check exact outputs instead of eyeballing them.

  python -m tests.fixtures.lecture out_dir
"""

import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 720


@dataclass
class Slide:
    kind: str  # slide | code | whiteboard
    title: str
    lines: list[str]
    spoken: str
    start_s: float = 0.0
    end_s: float = 0.0


SLIDES = [
    Slide(
        "slide",
        "Graph Search",
        ["Breadth first search", "Visits vertices level by level"],
        "Today we talk about graph search. Breadth first search visits vertices level by level.",
    ),
    Slide(
        "code",
        "def relax(u, v, w):",
        ["    if d[v] > d[u] + w:", "        d[v] = d[u] + w"],
        "Relaxing an edge means we lower the distance estimate when we find a shorter path.",
    ),
    Slide(
        "whiteboard",
        "Dijkstra",
        ["pop the smallest estimate", "weights must be non negative"],
        "Dijkstra always pulls out the vertex with the smallest estimate. "
        "This only works when every edge weight is non negative.",
    ),
    Slide(
        "slide",
        "Running Time",
        ["Binary heap: O(E log V)", "Fibonacci heap: O(E + V log V)"],
        "With a binary heap the running time is E log V.",
    ),
]

STYLE = {
    "slide": ("#FFFFFF", "#111111"),
    "code": ("#1E1E1E", "#D4D4D4"),
    "whiteboard": ("#23352C", "#E9EFE6"),
}


def _font(size: int, mono: bool = False) -> ImageFont.ImageFont:
    names = ["DejaVuSansMono.ttf"] if mono else ["DejaVuSans.ttf", "LiberationSans-Regular.ttf"]
    for name in names:
        for root in ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/liberation"):
            p = Path(root) / name
            if p.exists():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size=size)


def render(slide: Slide, path: Path) -> None:
    bg, fg = STYLE[slide.kind]
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    mono = slide.kind == "code"
    d.text((80, 80), slide.title, fill=fg, font=_font(64, mono))
    for i, line in enumerate(slide.lines):
        d.text((80, 220 + i * 80), line, fill=fg, font=_font(44, mono))
    img.save(path)


def _duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(out.stdout.strip())


def build(out_dir: Path, min_slide_s: float = 6.0) -> dict:
    """Write lecture.mp4 + truth.json into out_dir and return the truth dict."""
    if not shutil.which("espeak-ng") or not shutil.which("ffmpeg"):
        raise RuntimeError("needs espeak-ng and ffmpeg")
    out_dir.mkdir(parents=True, exist_ok=True)
    parts, t = [], 0.0
    for i, s in enumerate(SLIDES):
        png, wav, mp4 = (out_dir / f"s{i}.{ext}" for ext in ("png", "wav", "mp4"))
        render(s, png)
        subprocess.run(["espeak-ng", "-s", "150", "-w", str(wav), s.spoken], check=True)
        dur = max(_duration(wav) + 1.0, min_slide_s)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-loop",
                "1",
                "-i",
                str(png),
                "-i",
                str(wav),
                "-af",
                "apad",
                "-t",
                f"{dur:.3f}",
                "-r",
                "10",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-ar",
                "44100",
                "-ac",
                "1",
                str(mp4),
            ],
            check=True,
        )
        s.start_s, s.end_s = t, t + dur
        t += dur
        parts.append(mp4)
    listing = out_dir / "parts.txt"
    listing.write_text("".join(f"file '{p.name}'\n" for p in parts))
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            "-c",
            "copy",
            str(out_dir / "lecture.mp4"),
        ],
        check=True,
    )
    truth = {"duration_s": t, "slides": [asdict(s) for s in SLIDES]}
    (out_dir / "truth.json").write_text(json.dumps(truth, indent=2))
    return truth


if __name__ == "__main__":
    print(json.dumps(build(Path(sys.argv[1] if len(sys.argv) > 1 else "fixture")), indent=2))

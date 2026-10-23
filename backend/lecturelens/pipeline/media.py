"""ffmpeg wrappers: probe, pull audio, and capture a frame whenever the picture changes."""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


class MediaError(RuntimeError):
    pass


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise MediaError(f"{cmd[0]} failed: {proc.stderr.strip()[-500:]}")
    return proc


def probe(path: Path) -> dict:
    """Duration and whether the file really has video + audio streams.

    We trust ffprobe, not the file extension or the browser's content type.
    """
    out = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type",
            "-of",
            "default=nw=1",
            str(path),
        ]
    ).stdout
    kinds = re.findall(r"codec_type=(\w+)", out)
    dur = re.search(r"duration=([\d.]+)", out)
    return {
        "duration_s": float(dur.group(1)) if dur else None,
        "has_video": "video" in kinds,
        "has_audio": "audio" in kinds,
    }


def extract_audio(video: Path, wav: Path) -> Path:
    """16 kHz mono wav, which is what whisper wants."""
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(video),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(wav),
        ]
    )
    return wav


@dataclass
class Keyframe:
    t_s: float
    path: Path


def keyframes(
    video: Path,
    out_dir: Path,
    scene: float = 0.1,
    min_gap_s: float = 2.0,
    max_gap_s: float = 30.0,
    width: int = 1280,
) -> list[Keyframe]:
    """Grab the first frame, every scene change, and at least one frame per `max_gap_s`.

    Slides change abruptly so the scene score catches them. A professor slowly
    filling a board never trips it, hence the max-gap fallback. The threshold is
    low because dark slide -> dark board only scores ~0.17; min_gap_s stops a
    moving camera from firing every frame, and dedup cleans up the rest.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    select = (
        f"isnan(prev_selected_t)"
        f"+gt(scene\\,{scene})*gte(t-prev_selected_t\\,{min_gap_s})"
        f"+gte(t-prev_selected_t\\,{max_gap_s})"
    )
    proc = _run(
        [
            "ffmpeg",
            "-v",
            "info",
            "-i",
            str(video),
            "-an",
            "-vf",
            f"select='{select}',scale='min({width},iw)':-2,showinfo",
            "-fps_mode",
            "vfr",
            "-q:v",
            "3",
            str(out_dir / "f%05d.jpg"),
        ]
    )
    times = [float(t) for t in re.findall(r"pts_time:([\d.]+)", proc.stderr)]
    files = sorted(out_dir.glob("f*.jpg"))
    if len(times) != len(files):
        raise MediaError(f"showinfo saw {len(times)} frames but {len(files)} files were written")
    return [Keyframe(t, f) for t, f in zip(times, files, strict=True)]

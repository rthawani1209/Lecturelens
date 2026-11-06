"""ffmpeg wrappers: probe, pull audio, and capture a frame whenever the picture changes."""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


class MediaError(RuntimeError):
    pass


# Box types that can open an MP4/MOV file (ISO base media). Old QuickTime files may
# start with padding boxes rather than ftyp.
_ISO_BOXES = {b"ftyp", b"moov", b"mdat", b"free", b"skip", b"wide", b"pnot"}
_MATROSKA = b"\x1a\x45\xdf\xa3"  # mkv and webm


def looks_like_video(head: bytes) -> bool:
    """Cheap check on the first bytes of a file, before we store gigabytes of it.

    It only rules out obvious non-videos (a PDF renamed .mp4); ffprobe in the
    pipeline still decides whether the file actually plays.
    """
    return head.startswith(_MATROSKA) or (len(head) >= 8 and head[4:8] in _ISO_BOXES)


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
            "format=format_name,duration:stream=codec_name,codec_type",
            "-of",
            "default=nw=1",
            str(path),
        ]
    ).stdout
    streams = re.findall(r"codec_name=(\w+)\s+codec_type=(\w+)", out)
    first = {}
    for name, kind in streams:
        first.setdefault(kind, name)
    dur = re.search(r"duration=([\d.]+)", out)
    fmt = re.search(r"format_name=([\w,]+)", out)
    return {
        "format": fmt.group(1) if fmt else "",
        "duration_s": float(dur.group(1)) if dur else None,
        "has_video": "video" in first,
        "has_audio": "audio" in first,
        "video_codec": first.get("video"),
        "audio_codec": first.get("audio"),
    }


# Containers every current browser plays. Anything else (mkv, mostly) gets its
# streams copied into one of these, which takes seconds and doesn't re-encode.
BROWSER_CONTAINERS = {".mp4", ".m4v", ".mov", ".webm"}


def plays_as_is(ext: str, info: dict) -> bool:
    """Whether the stored file can go to the browser untouched. Goes by what ffprobe
    found inside, so an mkv someone renamed to .mp4 still gets remuxed."""
    if ext not in BROWSER_CONTAINERS:
        return False
    if ext == ".webm":
        return "webm" in info["format"] and info["video_codec"] in {"vp8", "vp9", "av1"}
    return "mp4" in info["format"].split(",")


def browser_container(info: dict) -> tuple[str, bool] | None:
    """Where the streams can go so a browser plays them: (".mp4" or ".webm", whether
    the audio has to be re-encoded). The video is always copied as it is; None
    means it would need a full re-encode, which we don't do."""
    v, a = info["video_codec"], info["audio_codec"]
    if v in {"vp8", "vp9", "av1"} and a in {None, "opus", "vorbis"}:
        return ".webm", False
    if v in {"h264", "hevc", "av1"}:
        # audio is small, so anything mp4 can't hold (opus, flac, ac3...) becomes aac
        return ".mp4", a not in {None, "aac", "mp3"}
    return None


def remux(src: Path, dst: Path, audio_to_aac: bool = False) -> Path:
    audio = ["-c:a", "aac", "-b:a", "128k"] if audio_to_aac else ["-c:a", "copy"]
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(src),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-c:v",
            "copy",
            *audio,
            "-movflags",
            "+faststart",
            str(dst),
        ]
    )
    return dst


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


def black_bars(video: Path, duration_s: float | None) -> str | None:
    """A crop filter that removes black bars, or None if there aren't any.

    A phone held upright to film a landscape screen leaves the slide in a strip
    in the middle; the bars would dilute every scene score below the threshold.
    Samples a few seconds at three points instead of decoding the whole file.
    """
    boxes = []
    for frac in (0.1, 0.5, 0.9):
        start = (duration_s or 0) * frac
        err = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "info",
                "-ss",
                f"{start:.2f}",
                "-t",
                "2",
                "-i",
                str(video),
                "-an",
                "-vf",
                "cropdetect=24:2:0",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
        ).stderr
        found = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", err)
        size = re.search(r"Stream .*Video:.*?, (\d{2,5})x(\d{2,5})", err)
        if found and size:
            boxes.append([int(v) for v in found[-1]])
            full_w, full_h = int(size.group(1)), int(size.group(2))
    if not boxes:
        return None
    # the union of what each sample showed, so a bright slide isn't cut off by a dark one
    x = min(b[2] for b in boxes)
    y = min(b[3] for b in boxes)
    w = max(b[2] + b[0] for b in boxes) - x
    h = max(b[3] + b[1] for b in boxes) - y
    if w * h > 0.8 * full_w * full_h or w < 64 or h < 64:
        return None
    return f"crop={w}:{h}:{x}:{y}"


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
    crop = black_bars(video, probe(video)["duration_s"])
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
            f"{crop + ',' if crop else ''}select='{select}',scale='min({width},iw)':-2,showinfo",
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

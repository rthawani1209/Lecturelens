"""Read the text on a slide or board with Tesseract."""

import logging
import os
import re
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

# Tesseract's own threading makes one small image slower, and on a busy worker
# (whisper, ffmpeg) the threads fight each other until frames time out.
_ENV = {**os.environ, "OMP_THREAD_LIMIT": "1"}


def ocr(path: Path, timeout_s: float = 30.0) -> str:
    try:
        proc = subprocess.run(
            ["tesseract", str(path), "stdout", "--psm", "3", "-l", "eng"],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=_ENV,
        )
    except subprocess.TimeoutExpired:
        # one stuck frame (a busy machine, a noisy image) isn't worth failing the lecture
        log.warning("OCR timed out on %s", path.name)
        return ""
    if proc.returncode != 0:
        return ""
    return clean(proc.stdout)


def clean(text: str) -> str:
    lines = []
    for line in text.splitlines():
        line = " ".join(line.split())
        # tesseract hallucinates short junk on noisy frames (a blurry face, a projector edge)
        if len(re.sub(r"[^A-Za-z0-9]", "", line)) >= 3:
            lines.append(line)
    return "\n".join(lines)

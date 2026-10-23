"""Read the text on a slide or board with Tesseract."""

import re
import subprocess
from pathlib import Path


def ocr(path: Path, timeout_s: float = 30.0) -> str:
    proc = subprocess.run(
        ["tesseract", str(path), "stdout", "--psm", "3", "-l", "eng"],
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
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

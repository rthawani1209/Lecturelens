"""Drop near-duplicate keyframes.

The scene detector also fires on a camera cut back to the same slide. Two checks:

- dhash: a 64-bit perceptual hash, stored per frame for fast "seen this before?"
  lookups across a whole course.
- signature: a 64x36 grayscale thumbnail. Consecutive slides from one template
  often share a layout, so a 64-bit hash can't tell them apart, but changed text
  still changes a few cells a lot, while video noise changes every cell a little.
"""

from pathlib import Path

import numpy as np
from PIL import Image


def dhash(path: Path | Image.Image, size: int = 8, margin: float = 1.0) -> int:
    img = path if isinstance(path, Image.Image) else Image.open(path)
    small = img.convert("F").resize((size + 1, size), Image.Resampling.BOX)
    g = np.asarray(small, dtype=np.float32)
    # slides are mostly flat background; without a margin, sensor noise decides
    # the bits there and two shots of the same slide look different
    bits = (g[:, 1:] - g[:, :-1] > margin).flatten()
    return int(np.packbits(bits).view(">u8")[0])


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def signature(path: Path | Image.Image) -> np.ndarray:
    img = path if isinstance(path, Image.Image) else Image.open(path)
    return np.asarray(img.convert("L").resize((64, 36), Image.Resampling.BOX), dtype=np.float32)


def same_picture(a: np.ndarray, b: np.ndarray, threshold: float = 0.01) -> bool:
    """Same if under 1% of thumbnail cells changed by more than 20 gray levels.

    Counting changed cells (instead of averaging the difference) catches a new
    line of text on an otherwise identical slide; noise never moves a cell that far.
    """
    return float(np.mean(np.abs(a - b) > 20)) < threshold


def dedupe(signatures: list[np.ndarray], threshold: float = 0.01) -> list[int]:
    """Indices to keep. A frame is dropped if it matches the last kept frame."""
    keep: list[int] = []
    for i, sig in enumerate(signatures):
        if not keep or not same_picture(sig, signatures[keep[-1]], threshold):
            keep.append(i)
    return keep


def to_signed(h: int) -> int:
    """Postgres bigint is signed."""
    return h - (1 << 64) if h >= 1 << 63 else h

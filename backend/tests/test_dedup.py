import numpy as np
from PIL import Image, ImageDraw

from lecturelens.pipeline.dedup import dedupe, dhash, hamming, signature, to_signed


def _slide(title: str, noise: float = 0.0) -> Image.Image:
    img = Image.new("RGB", (640, 360), "white")
    d = ImageDraw.Draw(img)
    d.rectangle((40, 40, 600, 100), fill="black")
    d.text((60, 150), title, fill="black")
    d.rectangle((40, 220, 40 + 50 * len(title), 300), fill="gray")
    if noise:
        arr = np.asarray(img, dtype=np.float32)
        arr += np.random.default_rng(1).normal(0, noise, arr.shape)
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    return img


def test_same_slide_with_noise_is_close_different_slide_is_far():
    a, a_noisy, b = dhash(_slide("Graphs")), dhash(_slide("Graphs", noise=8)), dhash(_slide("BFS"))
    assert hamming(a, a_noisy) <= 6
    assert hamming(a, b) > 6


def test_dedupe_keeps_first_of_each_run():
    a, b = _slide("Graphs"), _slide("Shortest paths")
    sigs = [signature(x) for x in (a, _slide("Graphs", noise=8), b, b, a)]
    assert dedupe(sigs) == [0, 2, 4]


def test_same_layout_different_text_is_not_a_duplicate():
    # same template, only the words change: the 64-bit hash can't see this
    sigs = [signature(_slide("Dijkstra")), signature(_slide("Bellman"))]
    assert dedupe(sigs) == [0, 1]


def test_to_signed_fits_bigint():
    assert to_signed(2**64 - 1) == -1
    assert to_signed(5) == 5

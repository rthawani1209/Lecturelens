"""Time the CLIP teacher on CPU, for comparison with the student in results.json.
Run with the backend venv (onnxruntime):  python ml/tagger/bench_clip.py
"""

import json
import time
from pathlib import Path

import numpy as np
from PIL import Image

from lecturelens.embed import ClipEmbedder, clip_preprocess


def per_frame_ms(fn, x: np.ndarray, reps: int) -> float:
    fn(x)  # warm up
    t = time.perf_counter()
    for _ in range(reps):
        fn(x)
    return (time.perf_counter() - t) / reps / len(x) * 1000


def main() -> None:
    frames = sorted(Path("data/storage/lectures").rglob("*.jpg"))[:32]
    clip = ClipEmbedder(Path("models/clip"))
    pixels = np.stack([clip_preprocess(Image.open(p)) for p in frames])

    def run(x):
        return clip.image.run(None, {"pixel_values": x})

    print(
        json.dumps(
            {
                "clip_ms_per_frame_single": per_frame_ms(run, pixels[:1], 20),
                "clip_ms_per_frame_batch32": per_frame_ms(run, pixels, 3),
                "clip_image_onnx_mb": round(Path("models/clip/image.onnx").stat().st_size / 1e6, 1),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

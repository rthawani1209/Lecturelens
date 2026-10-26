"""What kind of frame is this: slide, code, whiteboard, diagram, professor or other?

The real tagger is the MobileNetV3 model trained in ml/tagger and served by
TF Serving (TAGGER_URL). Without it, a linear probe on the CLIP vectors we
already store does the job a little slower and slightly less well, so local dev
and tests work with no extra service.
"""

from functools import lru_cache
from pathlib import Path

import httpx
import numpy as np
from PIL import Image

from .config import get_settings

SIZE = 224
_PROBE = Path(__file__).parent / "assets" / "tag_probe.npz"


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - x.max(-1, keepdims=True))
    return e / e.sum(-1, keepdims=True)


@lru_cache(maxsize=1)
def _probe() -> tuple[np.ndarray, np.ndarray, list[str]]:
    data = np.load(_PROBE)
    return data["w"], data["b"], [str(t) for t in data["tags"]]


def tags() -> list[str]:
    return _probe()[2]


def probe_scores(clip_vectors: np.ndarray) -> np.ndarray:
    w, b, _ = _probe()
    return _softmax(clip_vectors @ w + b)


def serving_scores(
    images: list[Path], url: str, batch: int = 16, http: httpx.Client | None = None
) -> np.ndarray:
    """Ask TF Serving's REST API. Frames are squashed to 224x224, like in training."""
    out = []
    with http or httpx.Client(timeout=60) as http:
        for i in range(0, len(images), batch):
            pixels = [
                np.asarray(Image.open(p).convert("RGB").resize((SIZE, SIZE), Image.BILINEAR))
                for p in images[i : i + batch]
            ]
            r = http.post(
                f"{url}/v1/models/tagger:predict",
                json={"instances": [p.tolist() for p in pixels]},
            )
            r.raise_for_status()
            out.append(
                np.asarray(
                    [p["tags"] if isinstance(p, dict) else p for p in r.json()["predictions"]],
                    np.float32,
                )
            )
    return np.concatenate(out) if out else np.zeros((0, len(tags())), np.float32)


def tagger_url() -> str:
    return get_settings().tagger_url.rstrip("/")

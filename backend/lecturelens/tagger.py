"""What kind of frame is this: slide, code, whiteboard, diagram, professor or other?

The real tagger is the MobileNetV3 model trained in ml/tagger and served by
TF Serving (TAGGER_URL). Without it, or when it's down, a linear probe on the CLIP
vectors we already store does the job (same accuracy on our test set, but it needs
the 350 MB CLIP model), so local dev and tests work with no extra service.
"""

import base64
import json
from functools import lru_cache
from pathlib import Path

import httpx
import numpy as np

from .config import get_settings

_PROBE = Path(__file__).parent / "assets" / "tag_probe.npz"


class TagOrderError(RuntimeError):
    """The served model's outputs aren't in the order we name them."""


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


@lru_cache(maxsize=4)
def check_model_tags(model_root: Path) -> None:
    """The exported model ships tags.json; refuse to use it if its order differs from ours."""
    versions = sorted(
        (p for p in model_root.glob("*") if p.name.isdigit()), key=lambda p: int(p.name)
    )
    if not versions:
        raise TagOrderError(f"no tagger model under {model_root}")
    served = json.loads((versions[-1] / "tags.json").read_text())
    if served != tags():
        raise TagOrderError(f"model tags {served} != backend tags {tags()}")


def serving_scores(
    images: list[Path], url: str, batch: int = 32, http: httpx.Client | None = None
) -> np.ndarray:
    """Ask TF Serving. We send the JPEG thumbnails as they are; the model resizes."""
    check_model_tags(Path(get_settings().models_dir) / "tagger")
    out = []
    with http or httpx.Client(timeout=60) as http:
        for i in range(0, len(images), batch):
            instances = [
                {"b64": base64.b64encode(p.read_bytes()).decode()} for p in images[i : i + batch]
            ]
            r = http.post(f"{url}/v1/models/tagger:predict", json={"instances": instances})
            r.raise_for_status()
            preds = [p["tags"] if isinstance(p, dict) else p for p in r.json()["predictions"]]
            out.append(np.asarray(preds, np.float32))
    return np.concatenate(out) if out else np.zeros((0, len(tags())), np.float32)


def tagger_url() -> str:
    return get_settings().tagger_url.rstrip("/")

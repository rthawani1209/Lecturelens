"""What kind of frame is this: slide, code, whiteboard, diagram, professor or other?

The real tagger is the MobileNetV3 model trained in ml/tagger, served by TF Serving
(TAGGER_URL). Without it, or when it's down, the same weights run in-process from an
ONNX copy (assets/tagger.onnx, made by ml/tagger/export_onnx.py), which is what ARM
hosts use since TF Serving has no ARM image. The linear probe on the stored CLIP
vectors is only a last resort if that file can't be loaded; it's weaker.
"""

import base64
import json
from functools import lru_cache
from pathlib import Path

import httpx
import numpy as np
from PIL import Image

from .config import get_settings

_PROBE = Path(__file__).parent / "assets" / "tag_probe.npz"
_ONNX = Path(__file__).parent / "assets" / "tagger.onnx"
SIZE = 224


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


@lru_cache(maxsize=1)
def _onnx_session():
    import onnxruntime as ort

    sess = ort.InferenceSession(str(_ONNX), providers=["CPUExecutionProvider"])
    meta = sess.get_modelmeta().custom_metadata_map
    if json.loads(meta.get("tags", "null")) != tags():
        raise TagOrderError(f"onnx tagger tags {meta.get('tags')} != backend tags {tags()}")
    return sess


def _pixels(path: Path) -> np.ndarray:
    # squashed to 224x224 with PIL bilinear, exactly as ml/tagger/train.py did
    with Image.open(path) as img:
        return np.asarray(img.convert("RGB").resize((SIZE, SIZE), Image.BILINEAR))


def onnx_scores(images: list[Path], batch: int = 32) -> np.ndarray:
    """The trained tagger, run in-process with onnxruntime."""
    sess = _onnx_session()
    out = [
        sess.run(["tags"], {"image": np.stack([_pixels(p) for p in images[i : i + batch]])})[0]
        for i in range(0, len(images), batch)
    ]
    return np.concatenate(out) if out else np.zeros((0, len(tags())), np.float32)


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

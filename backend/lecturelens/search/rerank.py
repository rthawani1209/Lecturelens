"""Re-score the top fused candidates with the trained re-ranker.

The network is tiny (two hidden layers), so besides TF Serving (RERANKER_URL) the
backend can run the exact same weights in NumPy. That's the default, and the
fallback when TF Serving is down; a test checks both give the same scores.
"""

import logging
from functools import lru_cache
from pathlib import Path

import httpx
import numpy as np

from ..config import get_settings
from . import features

log = logging.getLogger(__name__)
ASSETS = Path(__file__).resolve().parents[1] / "assets"


@lru_cache(maxsize=2)
def _load(name: str) -> dict[str, np.ndarray]:
    data = dict(np.load(ASSETS / name))
    names = [str(f) for f in data.pop("features")]
    if names != features.FEATURES:
        # weights trained on a different feature list would score garbage silently
        raise RuntimeError(f"{name} was trained on different features; retrain it")
    return data


def available() -> bool:
    return (ASSETS / "rerank_mlp.npz").exists()


def mlp_scores(x: np.ndarray) -> np.ndarray:
    m = _load("rerank_mlp.npz")
    h = (x - m["mean"]) / np.sqrt(np.maximum(m["var"], 1e-12))
    h = np.maximum(h @ m["w1"] + m["b1"], 0)
    h = np.maximum(h @ m["w2"] + m["b2"], 0)
    return (h @ m["w3"] + m["b3"]).reshape(-1)


def lr_scores(x: np.ndarray) -> np.ndarray:
    m = _load("rerank_lr.npz")
    return ((x - m["mean"]) / m["scale"]) @ m["coef"] + m["intercept"][0]


def serving_scores(x: np.ndarray, url: str, http: httpx.Client | None = None) -> np.ndarray:
    with http or httpx.Client(timeout=10) as http:
        r = http.post(f"{url}/v1/models/reranker:predict", json={"instances": x.tolist()})
        r.raise_for_status()
        return np.asarray(r.json()["predictions"], np.float32).reshape(-1)


def scores(x: np.ndarray, model: str = "mlp") -> np.ndarray:
    if model == "lr":
        return lr_scores(x)
    if url := get_settings().reranker_url.rstrip("/"):
        try:
            return serving_scores(x, url)
        except (httpx.HTTPError, ValueError) as e:
            log.warning("reranker at %s failed (%s), scoring in NumPy", url, e)
    return mlp_scores(x)

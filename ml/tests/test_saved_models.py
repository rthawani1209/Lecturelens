"""Load the SavedModels TF Serving runs and check they answer like the backend expects.

ml/.venv/bin/python -m pytest ml/tests
"""

import io
import json
import re
from pathlib import Path

import numpy as np
import pytest
import tensorflow as tf
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
FEATURES = ROOT / "backend/lecturelens/search/features.py"


def _latest(name: str) -> Path:
    versions = sorted((ROOT / "models" / name).glob("*/saved_model.pb"))
    if not versions:
        pytest.skip(f"no {name} model, run scripts/get_models.sh")
    return versions[-1].parent


def _backend_list(name: str) -> list[str]:
    # read the list from source so this env doesn't need the backend installed
    m = re.search(rf"^{name} = (\[.*?\])", FEATURES.read_text(), re.M | re.S)
    return json.loads(m.group(1).replace("'", '"'))


def test_tagger_bytes_and_pixels_signatures_agree():
    path = _latest("tagger")
    assert json.loads((path / "tags.json").read_text()) == _backend_list("TAGS")
    model = tf.saved_model.load(str(path))

    img = Image.new("RGB", (224, 224), "white")
    ImageDraw.Draw(img).text((20, 100), "def relax(u, v, w):", fill="black")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95)

    by_bytes = model.signatures["serving_default"](image_bytes=tf.constant([buf.getvalue()]))
    pixels = np.asarray(Image.open(buf))[None]
    by_pixels = model.signatures["pixels"](image=tf.constant(pixels, tf.uint8))
    a, b = by_bytes["tags"].numpy(), by_pixels["tags"].numpy()
    assert a.shape == (1, 6)
    np.testing.assert_allclose(a.sum(axis=1), 1, atol=1e-4)
    np.testing.assert_allclose(a, b, atol=0.02)


def test_reranker_export_matches_numpy_scores(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    monkeypatch.syspath_prepend(str(ROOT / "ml/rerank"))
    from export import build, export

    model, names = build()
    export(model, names, tmp_path / "1")
    served = tf.saved_model.load(str(tmp_path / "1")).signatures["serving_default"]
    fixed = json.loads((ROOT / "backend/tests/data/rerank_fixed.json").read_text())
    out = served(features=tf.constant(fixed["inputs"], tf.float32))["score"].numpy()
    np.testing.assert_allclose(out, fixed["scores"], atol=1e-4)
    assert json.loads((tmp_path / "1/features.json").read_text()) == names

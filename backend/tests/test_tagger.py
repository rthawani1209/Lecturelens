import base64
import json

import httpx
import numpy as np
import pytest
from PIL import Image

from lecturelens import tagger
from lecturelens.config import get_settings


def test_probe_gives_a_distribution_per_frame():
    rng = np.random.default_rng(0)
    v = rng.normal(size=(5, 512)).astype(np.float32)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    scores = tagger.probe_scores(v)
    assert scores.shape == (5, len(tagger.tags()))
    assert np.allclose(scores.sum(1), 1, atol=1e-5)
    assert tagger.tags()[:3] == ["slide", "code", "whiteboard"]


@pytest.fixture
def model_dir(tmp_path, monkeypatch):
    """A fake exported model: TF Serving's <version>/ layout with tags.json."""
    (tmp_path / "tagger" / "7").mkdir(parents=True)
    (tmp_path / "tagger" / "7" / "tags.json").write_text(json.dumps(tagger.tags()))
    monkeypatch.setenv("MODELS_DIR", str(tmp_path))
    get_settings.cache_clear()
    tagger.check_model_tags.cache_clear()
    yield tmp_path / "tagger"
    get_settings.cache_clear()
    tagger.check_model_tags.cache_clear()


def test_serving_client_sends_jpeg_bytes_in_batches(tmp_path, model_dir):
    paths = []
    for i in range(3):
        paths.append(tmp_path / f"{i}.jpg")
        Image.new("RGB", (640, 360), (i * 80, 0, 0)).save(paths[-1])
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models/tagger:predict"
        instances = json.loads(request.content)["instances"]
        seen.append(len(instances))
        assert base64.b64decode(instances[0]["b64"]) == paths[len(seen) * 2 - 2].read_bytes()
        k = len(tagger.tags())
        return httpx.Response(200, json={"predictions": [[1 / k] * k for _ in instances]})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    scores = tagger.serving_scores(paths, "http://tf", batch=2, http=http)
    assert seen == [2, 1]
    assert scores.shape == (3, len(tagger.tags()))


def test_model_with_different_tag_order_is_refused(model_dir):
    tagger.check_model_tags(model_dir)  # matches: fine
    newer = model_dir / "12"
    newer.mkdir()
    (newer / "tags.json").write_text(json.dumps(list(reversed(tagger.tags()))))
    tagger.check_model_tags.cache_clear()
    with pytest.raises(tagger.TagOrderError):
        tagger.check_model_tags(model_dir)

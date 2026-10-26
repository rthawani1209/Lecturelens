import httpx
import numpy as np
from PIL import Image

from lecturelens import tagger


def test_probe_gives_a_distribution_per_frame():
    rng = np.random.default_rng(0)
    v = rng.normal(size=(5, 512)).astype(np.float32)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    scores = tagger.probe_scores(v)
    assert scores.shape == (5, len(tagger.tags()))
    assert np.allclose(scores.sum(1), 1, atol=1e-5)
    assert tagger.tags()[:3] == ["slide", "code", "whiteboard"]


def test_serving_client_sends_224px_frames_in_batches(tmp_path):
    paths = []
    for i in range(3):
        paths.append(tmp_path / f"{i}.jpg")
        Image.new("RGB", (640, 360), (i * 80, 0, 0)).save(paths[-1])
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models/tagger:predict"
        instances = __import__("json").loads(request.content)["instances"]
        seen.append(len(instances))
        assert np.asarray(instances[0]).shape == (224, 224, 3)
        k = len(tagger.tags())
        return httpx.Response(200, json={"predictions": [[1 / k] * k for _ in instances]})

    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://tf")
    scores = tagger.serving_scores(paths, "http://tf", batch=2, http=http)
    assert seen == [2, 1]
    assert scores.shape == (3, len(tagger.tags()))

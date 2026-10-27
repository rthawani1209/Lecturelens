import importlib.util
import json
from pathlib import Path

import httpx
import numpy as np

from lecturelens.config import get_settings
from lecturelens.search import features, rerank

ROOT = Path(__file__).resolve().parents[2]
FIXED = json.loads((Path(__file__).parent / "data" / "rerank_fixed.json").read_text())


def _gate():
    spec = importlib.util.spec_from_file_location("gate", ROOT / "ml/rerank/gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_numpy_forward_matches_keras_on_fixed_inputs():
    # scores Keras gave for these exact rows at training time
    x = np.array(FIXED["inputs"], np.float32)
    assert x.shape[1] == len(features.FEATURES)
    np.testing.assert_allclose(rerank.mlp_scores(x), FIXED["scores"], atol=1e-4)


def test_baseline_loads_and_scores_every_row():
    x = np.array(FIXED["inputs"], np.float32)
    assert rerank.lr_scores(x).shape == (len(x),)


def test_regression_gate_passes_for_the_committed_model():
    gate = _gate()
    results = json.loads(gate.RESULTS.read_text())
    accepted = json.loads(gate.ACCEPTED.read_text())
    assert gate.check(results, accepted) == []
    # the weights shipped in assets are the ones the gate accepted
    assert json.loads(gate.TRAIN.read_text())["version"] == accepted["model_version"]


def test_gate_rejects_a_worse_model():
    gate = _gate()
    results = json.loads(gate.RESULTS.read_text())
    accepted = json.loads(gate.ACCEPTED.read_text())
    worse = json.loads(json.dumps(results))
    worse["results"]["hybrid+reranker"]["ndcg@10"] = results["results"]["hybrid"]["ndcg@10"]
    assert gate.check(worse, accepted)


def test_serving_client_and_fallback(monkeypatch):
    x = np.array(FIXED["inputs"], np.float32)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models/reranker:predict"
        rows = json.loads(request.content)["instances"]
        return httpx.Response(200, json={"predictions": [1.0] * len(rows)})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    assert rerank.serving_scores(x, "http://tf", http=http).tolist() == [1.0] * len(x)

    # TF Serving down: same scores as the NumPy path, no error
    monkeypatch.setenv("RERANKER_URL", "http://127.0.0.1:9")
    get_settings.cache_clear()
    try:
        np.testing.assert_allclose(rerank.scores(x), rerank.mlp_scores(x))
    finally:
        get_settings.cache_clear()

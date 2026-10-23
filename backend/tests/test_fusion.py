import numpy as np
import pytest

from lecturelens.search.fusion import (
    BruteForceIndex,
    cosine_sim,
    group_by_time,
    normalize,
    rrf,
    top_k,
)


def test_normalize_handles_zero_vector():
    out = normalize(np.array([[3.0, 4.0], [0.0, 0.0]]))
    assert out[0] == pytest.approx([0.6, 0.8])
    assert np.all(out[1] == 0)


def test_cosine_sim_hand_worked():
    q = np.array([[1.0, 0.0]])
    d = np.array([[1.0, 0.0], [0.0, 2.0], [1.0, 1.0], [-3.0, 0.0]])
    sims = cosine_sim(q, d)[0]
    assert sims == pytest.approx([1.0, 0.0, 1 / np.sqrt(2), -1.0], abs=1e-6)


def test_top_k_orders_best_first_and_clamps_k():
    scores = np.array([[0.1, 0.9, 0.5, 0.7]])
    assert top_k(scores, 2).tolist() == [[1, 3]]
    assert top_k(scores, 10).tolist() == [[1, 3, 2, 0]]


def test_brute_force_matches_full_sort():
    rng = np.random.default_rng(0)
    vecs = rng.normal(size=(500, 32))
    index = BruteForceIndex(vecs, ids=[f"s{i}" for i in range(500)])
    q = rng.normal(size=32)
    got = [i for i, _ in index.search(q, 10)]
    expected = np.argsort(-cosine_sim(q, vecs)[0])[:10]
    assert got == [f"s{i}" for i in expected]


def test_rrf_hand_worked():
    # a: 1/61            = 0.016393
    # b: 1/62 + 1/61     = 0.032522
    # c: 1/63 + 1/62     = 0.032002
    # d: 1/63            = 0.015873
    fused = rrf([["a", "b", "c"], ["b", "c", "d"]], k=60)
    assert [d for d, _ in fused] == ["b", "c", "a", "d"]
    assert dict(fused)["b"] == pytest.approx(1 / 62 + 1 / 61)


def test_rrf_weights():
    fused = rrf([["a"], ["b"]], weights=[1.0, 2.0])
    assert fused[0][0] == "b"


def test_group_by_time_merges_nearby_hits_in_same_lecture():
    hits = [
        ("L1", 100.0, 0.9),
        ("L1", 120.0, 0.8),  # same moment as the first
        ("L2", 110.0, 0.7),  # different lecture
        ("L1", 400.0, 0.6),
    ]
    assert group_by_time(hits, window_s=45) == [[0, 1], [2], [3]]

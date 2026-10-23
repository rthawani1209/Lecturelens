import pytest

from lecturelens.search.metrics import (
    dcg,
    evaluate,
    hit_at_k,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)

RANKED = ["a", "b", "c", "d"]
REL = {"b": 3, "c": 1, "z": 2}  # z was never retrieved


def test_recall_counts_relevant_found():
    assert recall_at_k(RANKED, REL, 2) == pytest.approx(1 / 3)
    assert recall_at_k(RANKED, REL, 4) == pytest.approx(2 / 3)


def test_hit_and_rr():
    assert hit_at_k(RANKED, REL, 1) == 0.0
    assert hit_at_k(RANKED, REL, 2) == 1.0
    assert reciprocal_rank(RANKED, REL) == 0.5
    assert reciprocal_rank(["x"], REL) == 0.0


def test_dcg_hand_worked():
    # (2^3-1)/log2(2) + (2^1-1)/log2(3) = 7 + 0.63093
    assert dcg([3, 1]) == pytest.approx(7.63093, abs=1e-5)
    assert dcg([]) == 0.0


def test_ndcg_hand_worked():
    rel = {"b": 3, "c": 1}
    # got  [0, 3, 1]: 7/log2(3) + 1/log2(4) = 4.41650 + 0.5     = 4.91650
    # best [3, 1, 0]: 7/1      + 1/log2(3) = 7       + 0.63093 = 7.63093
    assert ndcg_at_k(["a", "b", "c"], rel, 3) == pytest.approx(0.644285, abs=1e-5)
    assert ndcg_at_k(["b", "c", "a"], rel, 3) == pytest.approx(1.0)


def test_evaluate_averages_over_queries():
    out = evaluate({"q1": ["a", "b"], "q2": ["c"]}, {"q1": {"a": 1}, "q2": {"x": 1}}, ks=(1,))
    assert out["mrr"] == pytest.approx(0.5)
    assert out["hit@1"] == pytest.approx(0.5)

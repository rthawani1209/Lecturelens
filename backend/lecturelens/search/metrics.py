"""Ranking metrics used by the eval script and the model gates.

Every function takes `ranked`, the result ids best-first, and `relevance`, a
dict id -> graded relevance (0 = not relevant, 3 = exactly right). Ids missing
from `relevance` count as 0.
"""

from collections.abc import Hashable, Mapping, Sequence

import numpy as np


def recall_at_k(ranked: Sequence[Hashable], relevance: Mapping[Hashable, float], k: int) -> float:
    relevant = {d for d, r in relevance.items() if r > 0}
    if not relevant:
        return 0.0
    found = sum(1 for d in ranked[:k] if d in relevant)
    return found / len(relevant)


def hit_at_k(ranked: Sequence[Hashable], relevance: Mapping[Hashable, float], k: int) -> float:
    """1 if anything relevant shows up in the top k. Closer to what a student feels."""
    return float(any(relevance.get(d, 0) > 0 for d in ranked[:k]))


def reciprocal_rank(ranked: Sequence[Hashable], relevance: Mapping[Hashable, float]) -> float:
    for i, d in enumerate(ranked, start=1):
        if relevance.get(d, 0) > 0:
            return 1.0 / i
    return 0.0


def dcg(gains: Sequence[float]) -> float:
    """Discounted cumulative gain with the exponential gain used by most IR papers."""
    g = np.asarray(gains, dtype=np.float64)
    if g.size == 0:
        return 0.0
    discounts = np.log2(np.arange(2, g.size + 2))
    return float(np.sum((2.0**g - 1.0) / discounts))


def ndcg_at_k(ranked: Sequence[Hashable], relevance: Mapping[Hashable, float], k: int) -> float:
    gains = [relevance.get(d, 0) for d in ranked[:k]]
    ideal = sorted(relevance.values(), reverse=True)[:k]
    best = dcg(ideal)
    return dcg(gains) / best if best > 0 else 0.0


def evaluate(
    runs: Mapping[str, Sequence[Hashable]],
    qrels: Mapping[str, Mapping[Hashable, float]],
    ks: Sequence[int] = (5, 10),
) -> dict[str, float]:
    """Average every metric over queries. `runs` maps query id -> ranked ids."""
    rows = []
    for qid, rel in qrels.items():
        ranked = runs.get(qid, [])
        row = {"mrr": reciprocal_rank(ranked, rel)}
        for k in ks:
            row[f"recall@{k}"] = recall_at_k(ranked, rel, k)
            row[f"ndcg@{k}"] = ndcg_at_k(ranked, rel, k)
            row[f"hit@{k}"] = hit_at_k(ranked, rel, k)
        rows.append(row)
    if not rows:
        return {}
    return {key: float(np.mean([r[key] for r in rows])) for key in rows[0]}

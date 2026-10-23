"""Vector math and rank fusion, written directly in NumPy.

pgvector does the real nearest-neighbour search in production; the brute-force
index here is the ground truth we check its recall against.
"""

from collections.abc import Hashable, Sequence

import numpy as np


def normalize(x: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    """L2-normalize rows (or a single vector)."""
    x = np.asarray(x, dtype=np.float32)
    norms = np.linalg.norm(x, axis=-1, keepdims=True)
    return x / np.maximum(norms, eps)


def cosine_sim(queries: np.ndarray, docs: np.ndarray) -> np.ndarray:
    """Cosine similarity between every query row and every doc row -> (n_q, n_d)."""
    q = normalize(np.atleast_2d(queries))
    d = normalize(np.atleast_2d(docs))
    return q @ d.T


def top_k(scores: np.ndarray, k: int) -> np.ndarray:
    """Indices of the k highest scores per row, best first.

    argpartition is O(n) per row, then we only sort the k survivors.
    """
    scores = np.atleast_2d(scores)
    k = min(k, scores.shape[1])
    if k <= 0:
        return np.empty((scores.shape[0], 0), dtype=np.int64)
    part = np.argpartition(-scores, k - 1, axis=1)[:, :k]
    order = np.argsort(-np.take_along_axis(scores, part, axis=1), axis=1, kind="stable")
    return np.take_along_axis(part, order, axis=1)


class BruteForceIndex:
    """Exact cosine search over a fixed matrix. Fine up to ~1M x 384 on a laptop."""

    def __init__(self, vectors: np.ndarray, ids: Sequence[Hashable] | None = None):
        self.vectors = normalize(vectors)
        self.ids = list(ids) if ids is not None else list(range(len(self.vectors)))
        if len(self.ids) != len(self.vectors):
            raise ValueError("ids and vectors must have the same length")

    def __len__(self) -> int:
        return len(self.ids)

    def search(self, query: np.ndarray, k: int) -> list[tuple[Hashable, float]]:
        sims = self.vectors @ normalize(query).reshape(-1)
        idx = top_k(sims[None, :], k)[0]
        return [(self.ids[i], float(sims[i])) for i in idx]


def rrf(
    rankings: Sequence[Sequence[Hashable]], k: int = 60, weights: Sequence[float] | None = None
) -> list[tuple[Hashable, float]]:
    """Reciprocal rank fusion: score(d) = sum_i w_i / (k + rank_i(d)), ranks start at 1.

    Only ranks matter, so it can merge lists whose raw scores live on different
    scales (BM25 vs cosine). Ties keep first-seen order.
    """
    if weights is None:
        weights = [1.0] * len(rankings)
    if len(weights) != len(rankings):
        raise ValueError("need one weight per ranking")
    scores: dict[Hashable, float] = {}
    for ranking, w in zip(rankings, weights, strict=True):
        for rank, doc in enumerate(ranking, start=1):
            scores[doc] = scores.get(doc, 0.0) + w / (k + rank)
    return sorted(scores.items(), key=lambda kv: -kv[1])


def group_by_time(
    hits: Sequence[tuple[Hashable, float, float]], window_s: float = 45.0
) -> list[list[int]]:
    """Group hits (lecture_id, start_s, score) that land close together in one lecture.

    Returns groups as lists of indices into `hits`, ordered by each group's best
    score. Overlapping 30s windows otherwise show up as near-duplicate results.
    """
    order = sorted(range(len(hits)), key=lambda i: -hits[i][2])
    groups: list[list[int]] = []
    anchors: list[tuple[Hashable, float]] = []
    for i in order:
        lec, t, _ = hits[i]
        for g, (alec, at) in enumerate(anchors):
            if alec == lec and abs(at - t) <= window_s:
                groups[g].append(i)
                break
        else:
            groups.append([i])
            anchors.append((lec, t))
    return groups

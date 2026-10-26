"""Label every stored frame with a CLIP "teacher". The small TensorFlow tagger then
learns from these labels (distillation), so nobody hand-labels thousands of frames.

Two teachers are compared on the hand-checked frames from the held-out lectures:
  zero-shot    cosine similarity between the frame and a few text prompts per tag
  linear probe a softmax regression on CLIP vectors, trained (in NumPy) on the
               hand-checked frames from the other lectures

Run with the backend venv; it reuses the CLIP vectors already in Postgres:
    python ml/tagger/pseudo_label.py
"""

import argparse
import csv
import json
from pathlib import Path

import numpy as np

from lecturelens.db import connection
from lecturelens.embed import clip_embedder

TAGS = ["slide", "code", "whiteboard", "diagram", "professor", "other"]
# same held-out lectures as the search eval, so nothing about them leaks into training
TEST_LECTURES = {1, 4, 7, 10, 13, 16, 19}

# a few phrasings per tag, averaged; single prompts are noticeably worse
PROMPTS = {
    "slide": [
        "a presentation slide with a title and bullet points",
        "a projected lecture slide with text",
        "a powerpoint slide",
    ],
    "code": [
        "source code on a screen",
        "a slide showing python code",
        "a programming code listing",
    ],
    "whiteboard": [
        "handwritten math equations on a chalkboard",
        "a blackboard covered in chalk writing",
        "handwritten notes on a whiteboard",
    ],
    "diagram": [
        "a diagram of a graph with nodes and edges",
        "a tree diagram drawn on a blackboard",
        "a drawing of arrays and boxes",
    ],
    "professor": [
        "a professor talking in front of the class",
        "a person giving a lecture, seen from the audience",
        "a close-up of a teacher speaking",
    ],
    "other": [
        "a plain red title card",
        "a blank black screen",
        "a title screen with a university logo",
    ],
}
LOGIT_SCALE = 100.0  # CLIP's learned temperature


def softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - x.max(-1, keepdims=True))
    return e / e.sum(-1, keepdims=True)


def zero_shot(emb: np.ndarray) -> np.ndarray:
    clip = clip_embedder()
    vecs = []
    for tag in TAGS:
        v = clip.embed_texts(PROMPTS[tag]).mean(0)
        vecs.append(v / np.linalg.norm(v))
    return softmax(LOGIT_SCALE * emb @ np.stack(vecs).T)


def train_probe(
    x: np.ndarray, y: np.ndarray, l2: float = 1e-3, lr: float = 0.5, steps: int = 2000
) -> tuple[np.ndarray, np.ndarray]:
    """Multinomial logistic regression with plain gradient descent.

    Classes are weighted by inverse frequency so rare tags (code) still count.
    """
    n, k = len(x), len(TAGS)
    onehot = np.eye(k)[y]
    counts = np.bincount(y, minlength=k).astype(float)
    weight = (n / (k * np.maximum(counts, 1)))[y][:, None]
    w, b = np.zeros((x.shape[1], k)), np.zeros(k)
    xs = x * LOGIT_SCALE**0.5  # unit vectors give tiny logits otherwise
    for _ in range(steps):
        g = weight * (softmax(xs @ w + b) - onehot) / n
        w -= lr * (xs.T @ g + l2 * w)
        b -= lr * g.sum(0)
    return w * LOGIT_SCALE**0.5, b


def accuracy(probs: np.ndarray, y: np.ndarray) -> float:
    return float((probs.argmax(1) == y).mean())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hand", type=Path, default=Path("ml/tagger/data/hand_labels.csv"))
    ap.add_argument("--out", type=Path, default=Path("ml/tagger/data/pseudo_labels.csv"))
    # the backend falls back to this probe when TF Serving isn't running
    ap.add_argument("--probe", type=Path, default=Path("backend/lecturelens/assets/tag_probe.npz"))
    args = ap.parse_args()

    with connection() as conn:
        rows = conn.execute(
            "SELECT f.id, f.t_s, f.thumb_key, f.clip_emb, l.position"
            "  FROM frames f JOIN lectures l ON l.id = f.lecture_id"
            " WHERE f.clip_emb IS NOT NULL ORDER BY l.position, f.t_s"
        ).fetchall()
    emb = np.stack([r["clip_emb"].to_numpy() for r in rows]).astype(np.float64)
    index = {r["id"]: i for i, r in enumerate(rows)}
    test = np.array([r["position"] in TEST_LECTURES for r in rows])

    hand = {int(r["frame_id"]): TAGS.index(r["label"]) for r in csv.DictReader(open(args.hand))}
    hi = np.array([index[f] for f in hand])
    hy = np.array(list(hand.values()))
    fit, held = ~test[hi], test[hi]

    zs = zero_shot(emb)
    w, b = train_probe(emb[hi[fit]], hy[fit])
    probe = softmax(emb @ w + b)
    report = {
        "hand_labeled": {"train": int(fit.sum()), "test": int(held.sum())},
        "test_accuracy": {
            "clip_zero_shot": accuracy(zs[hi[held]], hy[held]),
            "clip_linear_probe": accuracy(probe[hi[held]], hy[held]),
        },
    }
    print(json.dumps(report, indent=2))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="") as f:
        out = csv.writer(f)
        out.writerow(["frame_id", "lecture", "split", "t_s", "thumb_key", "label", "conf", *TAGS])
        for r, p, t in zip(rows, probe, test, strict=True):
            out.writerow(
                [
                    r["id"],
                    r["position"],
                    "test" if t else "train",
                    round(r["t_s"], 2),
                    r["thumb_key"],
                    TAGS[p.argmax()],
                    round(float(p.max()), 4),
                    *(round(float(x), 4) for x in p),
                ]
            )
    args.probe.parent.mkdir(parents=True, exist_ok=True)
    np.savez(args.probe, w=w.astype(np.float32), b=b.astype(np.float32), tags=np.array(TAGS))
    (args.out.parent / "teacher_report.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()

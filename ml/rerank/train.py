"""Train the search re-ranker: a small Keras network scored with a pairwise
(RankNet) loss, plus a scikit-learn logistic regression baseline.

    ml/.venv/bin/python ml/rerank/train.py

Reads ml/rerank/data/dataset.npz (build_dataset.py). Trains on generated queries
from the training lectures, early-stops on the hand-labeled val questions, and
writes the weights the backend uses (NumPy forward pass) plus a SavedModel for
TF Serving. Runs log to MLflow.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import keras
import mlflow
import numpy as np
import tensorflow as tf
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from lecturelens.search.metrics import ndcg_at_k  # noqa: E402

ASSETS = Path("backend/lecturelens/assets")


def groups(qid: np.ndarray) -> list[np.ndarray]:
    return [np.flatnonzero(qid == q) for q in np.unique(qid)]


def mean_ndcg(scores: np.ndarray, y: np.ndarray, qid: np.ndarray, k: int = 10) -> float:
    out = []
    for idx in groups(qid):
        if y[idx].max() <= 0:
            continue
        order = idx[np.argsort(-scores[idx], kind="stable")]
        out.append(ndcg_at_k(list(order), {i: y[i] for i in idx}, k))
    return float(np.mean(out))


def make_pairs(y: np.ndarray, qid: np.ndarray, rng: np.random.Generator, neg_per_pos: int):
    """(better, worse) index pairs inside each query."""
    a, b = [], []
    for idx in groups(qid):
        pos, neg = idx[y[idx] > 0], idx[y[idx] == 0]
        if not len(pos) or not len(neg):
            continue
        for p in pos:
            for n in rng.choice(neg, min(neg_per_pos, len(neg)), replace=False):
                a.append(p)
                b.append(n)
    return np.array(a), np.array(b)


def build_scorer(n_features: int, x_train: np.ndarray, hidden: int, dropout: float):
    norm = keras.layers.Normalization(name="norm")
    norm.adapt(x_train)
    inp = keras.Input((n_features,), name="features")
    h = norm(inp)
    h = keras.layers.Dense(hidden, activation="relu", name="dense1")(h)
    h = keras.layers.Dropout(dropout)(h)
    h = keras.layers.Dense(hidden // 2, activation="relu", name="dense2")(h)
    out = keras.layers.Dense(1, name="score")(h)
    return keras.Model(inp, keras.layers.Reshape(())(out), name="scorer")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=Path("ml/rerank/data/dataset.npz"))
    ap.add_argument("--export", type=Path, default=Path("models/reranker"))
    ap.add_argument("--hidden", type=int, default=32)
    ap.add_argument("--dropout", type=float, default=0.1)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--neg-per-pos", type=int, default=20)
    ap.add_argument("--seed", type=int, default=6006)
    args = ap.parse_args()
    keras.utils.set_random_seed(args.seed)
    rng = np.random.default_rng(args.seed)

    d = np.load(args.data)
    X, y, qid, names = d["X"], d["y"], d["qid"], [str(f) for f in d["features"]]
    meta = json.loads(args.data.with_suffix(".json").read_text())
    split = np.array([meta[q]["split"] for q in qid])
    tr, va, te = split == "train", split == "val", split == "test"
    print(f"rows train {tr.sum()} val {va.sum()} test {te.sum()}, features {len(names)}")

    # pointwise baseline: is this candidate from the right window?
    scaler = StandardScaler().fit(X[tr])
    lr = LogisticRegression(max_iter=2000, class_weight="balanced").fit(
        scaler.transform(X[tr]), y[tr] > 0
    )
    lr_scores = lr.decision_function(scaler.transform(X))

    scorer = build_scorer(len(names), X[tr], args.hidden, args.dropout)
    xa = keras.Input((len(names),), name="better")
    xb = keras.Input((len(names),), name="worse")
    # RankNet: P(better beats worse) = sigmoid(s_better - s_worse)
    diff = keras.layers.Subtract()([scorer(xa), scorer(xb)])
    pair_model = keras.Model([xa, xb], keras.layers.Activation("sigmoid")(diff))
    pair_model.compile(keras.optimizers.Adam(args.lr), loss="binary_crossentropy")

    tr_idx = np.flatnonzero(tr)
    best, best_weights, history = -1.0, None, []
    with mlflow.start_run(experiment_id=mlflow.set_experiment("reranker").experiment_id) as run:
        mlflow.log_params(vars(args) | {"features": len(names), "train_rows": int(tr.sum())})
        for epoch in range(args.epochs):
            # fresh negatives every epoch
            a, b = make_pairs(y[tr], qid[tr], rng, args.neg_per_pos)
            a, b = tr_idx[a], tr_idx[b]  # back to row numbers in X
            h = pair_model.fit([X[a], X[b]], np.ones(len(a)), batch_size=256, epochs=1, verbose=0)
            val = mean_ndcg(scorer.predict(X[va], verbose=0), y[va], qid[va])
            history.append(val)
            mlflow.log_metrics({"pair_loss": h.history["loss"][0], "val_ndcg10": val}, step=epoch)
            print(f"epoch {epoch:2d} loss {h.history['loss'][0]:.4f} val ndcg@10 {val:.4f}")
            if val > best:
                best, best_weights = val, scorer.get_weights()
            elif epoch - int(np.argmax(history)) >= 5:
                break
        scorer.set_weights(best_weights)

        nn = scorer.predict(X, verbose=0)
        fused = X[:, names.index("fused_score")]
        window = {
            split_name: {
                "rrf": mean_ndcg(fused[m], y[m], qid[m]),
                "logistic_regression": mean_ndcg(lr_scores[m], y[m], qid[m]),
                "reranker": mean_ndcg(nn[m], y[m], qid[m]),
            }
            for split_name, m in (("val", va), ("test", te))
        }
        print(json.dumps(window, indent=2))
        mlflow.log_metrics(
            {f"{s}_{k}_window_ndcg10": v for s, r in window.items() for k, v in r.items()}
        )

        # the backend runs the same network in NumPy; save exactly what it needs
        norm = scorer.get_layer("norm")
        dense = [scorer.get_layer(n).get_weights() for n in ("dense1", "dense2", "score")]
        ASSETS.mkdir(parents=True, exist_ok=True)
        np.savez(
            ASSETS / "rerank_mlp.npz",
            mean=np.asarray(norm.mean).reshape(-1),
            var=np.asarray(norm.variance).reshape(-1),
            w1=dense[0][0],
            b1=dense[0][1],
            w2=dense[1][0],
            b2=dense[1][1],
            w3=dense[2][0],
            b3=dense[2][1],
            features=np.array(names),
        )
        np.savez(
            ASSETS / "rerank_lr.npz",
            mean=scaler.mean_,
            scale=scaler.scale_,
            coef=lr.coef_[0],
            intercept=lr.intercept_,
            features=np.array(names),
        )
        # fixed inputs -> expected scores, so tests can catch a model or code change
        fixed = X[te][:8]
        Path("backend/tests/data").mkdir(parents=True, exist_ok=True)
        Path("backend/tests/data/rerank_fixed.json").write_text(
            json.dumps(
                {
                    "inputs": fixed.round(6).tolist(),
                    "scores": scorer.predict(fixed.round(6), verbose=0).round(6).tolist(),
                }
            )
            + "\n"
        )

        version = int(time.time())
        dst = args.export / str(version)
        export = keras.export.ExportArchive()
        export.track(scorer)
        export.add_endpoint(
            "serving_default",
            lambda features: {"score": scorer(features, training=False)},
            input_signature=[tf.TensorSpec([None, len(names)], tf.float32, name="features")],
        )
        export.write_out(str(dst))
        (dst / "features.json").write_text(json.dumps(names) + "\n")

        summary = {
            "window_ndcg10": window,
            "best_epoch": int(np.argmax(history)),
            "params": int(scorer.count_params()),
            "version": version,
            "mlflow_run_id": run.info.run_id,
            "features": names,
        }
        Path("ml/rerank/train_results.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(f"exported {dst}")


if __name__ == "__main__":
    main()

"""Rebuild the re-ranker SavedModel for TF Serving from the committed weights.

    ml/.venv/bin/python ml/rerank/export.py

The backend scores with backend/lecturelens/assets/rerank_mlp.npz in NumPy, so that
file is the source of truth. This writes the same network to models/reranker/<version>
without retraining, so there's no separate model release to keep in sync.
"""

import argparse
import json
from pathlib import Path

import keras
import numpy as np
import tensorflow as tf

WEIGHTS = Path("backend/lecturelens/assets/rerank_mlp.npz")


def build(weights: Path = WEIGHTS) -> tuple[keras.Model, list[str]]:
    d = np.load(weights)
    names = [str(f) for f in d["features"]]
    n, hidden = d["w1"].shape
    inp = keras.Input((n,), name="features")
    norm = keras.layers.Normalization(mean=d["mean"], variance=d["var"], name="norm")
    h = keras.layers.Dense(hidden, activation="relu", name="dense1")(norm(inp))
    h = keras.layers.Dense(d["w2"].shape[1], activation="relu", name="dense2")(h)
    out = keras.layers.Dense(1, name="score")(h)
    model = keras.Model(inp, keras.layers.Reshape(())(out), name="scorer")
    for i, layer in enumerate(("dense1", "dense2", "score"), start=1):
        model.get_layer(layer).set_weights([d[f"w{i}"], d[f"b{i}"]])
    return model, names


def export(model: keras.Model, names: list[str], dst: Path) -> None:
    archive = keras.export.ExportArchive()
    archive.track(model)
    archive.add_endpoint(
        "serving_default",
        lambda features: {"score": model(features, training=False)},
        input_signature=[tf.TensorSpec([None, len(names)], tf.float32, name="features")],
    )
    archive.write_out(str(dst))
    (dst / "features.json").write_text(json.dumps(names) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("models/reranker"))
    ap.add_argument("--version", type=int, default=1)
    args = ap.parse_args()
    model, names = build()
    dst = args.out / str(args.version)
    export(model, names, dst)
    print(f"exported {dst}")


if __name__ == "__main__":
    main()

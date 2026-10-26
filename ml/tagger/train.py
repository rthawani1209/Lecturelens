"""Train the frame tagger: MobileNetV3-Small, fine-tuned in Keras on the CLIP
teacher's soft labels (knowledge distillation).

    ml/.venv/bin/python ml/tagger/train.py --storage data/storage --export models/tagger

Only frames from training lectures are used. The held-out lectures are scored
against the hand-checked labels at the end. Runs are logged to MLflow (./mlruns).
"""

import argparse
import csv
import json
import time
from pathlib import Path

import keras
import mlflow
import numpy as np
import tensorflow as tf
from PIL import Image

TAGS = ["slide", "code", "whiteboard", "diagram", "professor", "other"]
SIZE = 224
VAL_LECTURES = {2, 20}  # early stopping only; the real test set is the hand labels


def load_images(paths: list[Path]) -> np.ndarray:
    out = np.zeros((len(paths), SIZE, SIZE, 3), np.uint8)
    for i, p in enumerate(paths):
        # squash the 16:9 frame instead of cropping, so text at the edges stays in
        out[i] = np.asarray(Image.open(p).convert("RGB").resize((SIZE, SIZE), Image.BILINEAR))
    return out


def build_model(dropout: float) -> tuple[keras.Model, keras.Model]:
    base = keras.applications.MobileNetV3Small(
        input_shape=(SIZE, SIZE, 3),
        include_top=False,
        weights="imagenet",
        pooling="avg",
        include_preprocessing=True,  # takes raw 0-255 pixels
    )
    augment = keras.Sequential(
        [
            keras.layers.RandomZoom(0.1),
            keras.layers.RandomTranslation(0.05, 0.05),
            keras.layers.RandomContrast(0.2),
        ],
        name="augment",
    )
    inputs = keras.Input((SIZE, SIZE, 3), dtype="uint8", name="image")
    x = keras.layers.Lambda(lambda t: tf.cast(t, tf.float32), name="to_float")(inputs)
    x = augment(x)
    x = base(x)
    x = keras.layers.Dropout(dropout)(x)
    outputs = keras.layers.Dense(len(TAGS), activation="softmax", name="tags")(x)
    return keras.Model(inputs, outputs, name="frame_tagger"), base


def macro_f1(pred: np.ndarray, y: np.ndarray) -> float:
    f1s = []
    for k in range(len(TAGS)):
        tp = np.sum((pred == k) & (y == k))
        fp, fn = np.sum((pred == k) & (y != k)), np.sum((pred != k) & (y == k))
        if tp + fp + fn:
            f1s.append(2 * tp / (2 * tp + fp + fn))
    return float(np.mean(f1s))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", type=Path, default=Path("ml/tagger/data/pseudo_labels.csv"))
    ap.add_argument("--hand", type=Path, default=Path("ml/tagger/data/hand_labels.csv"))
    ap.add_argument("--storage", type=Path, default=Path("data/storage"))
    ap.add_argument("--export", type=Path, default=Path("models/tagger"))
    ap.add_argument("--head-epochs", type=int, default=6)
    ap.add_argument("--tune-epochs", type=int, default=8)
    ap.add_argument("--unfreeze", type=int, default=40, help="layers of the base to fine-tune")
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--dropout", type=float, default=0.3)
    ap.add_argument("--seed", type=int, default=6006)
    args = ap.parse_args()
    keras.utils.set_random_seed(args.seed)

    rows = list(csv.DictReader(open(args.labels)))
    soft = np.array([[float(r[t]) for t in TAGS] for r in rows], np.float32)
    lecture = np.array([int(r["lecture"]) for r in rows])
    is_test = np.array([r["split"] == "test" for r in rows])
    is_val = ~is_test & np.isin(lecture, list(VAL_LECTURES))
    is_train = ~is_test & ~is_val
    images = load_images([args.storage / r["thumb_key"] for r in rows])
    print(f"train {is_train.sum()}  val {is_val.sum()}  test lectures {is_test.sum()} frames")

    hand = {r["frame_id"]: TAGS.index(r["label"]) for r in csv.DictReader(open(args.hand))}
    held = [i for i, r in enumerate(rows) if r["frame_id"] in hand and is_test[i]]
    hand_y = np.array([hand[rows[i]["frame_id"]] for i in held])

    model, base = build_model(args.dropout)
    mlflow.set_experiment("frame-tagger")
    with mlflow.start_run() as run:
        mlflow.log_params(vars(args) | {"train_frames": int(is_train.sum())})
        val = (images[is_val], soft[is_val])
        stop = keras.callbacks.EarlyStopping(patience=3, restore_best_weights=True)

        # 1) new head only, base frozen
        base.trainable = False
        model.compile(
            optimizer=keras.optimizers.Adam(1e-3),
            loss="categorical_crossentropy",
            metrics=["categorical_accuracy"],
        )
        h1 = model.fit(
            images[is_train],
            soft[is_train],
            batch_size=args.batch,
            epochs=args.head_epochs,
            validation_data=val,
            callbacks=[stop],
            verbose=2,
        )

        # 2) unfreeze the top of the base with a small learning rate.
        # BatchNorm stays frozen: our batches are too small to re-estimate its stats.
        base.trainable = True
        for layer in base.layers[: -args.unfreeze]:
            layer.trainable = False
        for layer in base.layers:
            if isinstance(layer, keras.layers.BatchNormalization):
                layer.trainable = False
        model.compile(
            optimizer=keras.optimizers.Adam(1e-4),
            loss="categorical_crossentropy",
            metrics=["categorical_accuracy"],
        )
        h2 = model.fit(
            images[is_train],
            soft[is_train],
            batch_size=args.batch,
            epochs=args.tune_epochs,
            validation_data=val,
            callbacks=[stop],
            verbose=2,
        )
        for step, (loss, acc) in enumerate(
            zip(
                h1.history["val_loss"] + h2.history["val_loss"],
                h1.history["val_categorical_accuracy"] + h2.history["val_categorical_accuracy"],
                strict=True,
            )
        ):
            mlflow.log_metrics({"val_loss": loss, "val_teacher_agreement": acc}, step=step)

        probs = model.predict(images[is_test], batch_size=64, verbose=0)
        teacher = soft[is_test].argmax(1)
        hand_pred = model.predict(images[held], verbose=0).argmax(1)
        teacher_hand = soft[held].argmax(1)

        # speed on CPU: one frame at a time (pipeline worst case) and batches of 32
        infer = tf.function(lambda x: model(x, training=False))
        one, batch = images[:1], images[:32]
        infer(one), infer(batch)
        t = time.perf_counter()
        for _ in range(50):
            infer(one)
        ms_one = (time.perf_counter() - t) / 50 * 1000
        t = time.perf_counter()
        for _ in range(5):
            infer(batch)
        ms_frame_batched = (time.perf_counter() - t) / 5 / 32 * 1000

        metrics = {
            "test_hand_accuracy": float((hand_pred == hand_y).mean()),
            "test_hand_macro_f1": macro_f1(hand_pred, hand_y),
            "teacher_hand_accuracy": float((teacher_hand == hand_y).mean()),
            "teacher_hand_macro_f1": macro_f1(teacher_hand, hand_y),
            "test_teacher_agreement": float((probs.argmax(1) == teacher).mean()),
            "ms_per_frame_single": ms_one,
            "ms_per_frame_batch32": ms_frame_batched,
            "params": int(model.count_params()),
        }
        mlflow.log_metrics(metrics)
        print(json.dumps(metrics, indent=2))

        # TF Serving layout: <name>/<version>/saved_model.pb. Augmentation layers are
        # no-ops at inference, so the served graph is just resize-free MobileNet + head.
        version = int(time.time())
        export_dir = args.export / str(version)
        export = keras.export.ExportArchive()
        export.track(model)
        export.add_endpoint(
            "serving_default",
            lambda image: {"tags": model(image, training=False)},
            input_signature=[tf.TensorSpec([None, SIZE, SIZE, 3], tf.uint8, name="image")],
        )
        export.write_out(str(export_dir))
        size_mb = sum(f.stat().st_size for f in export_dir.rglob("*") if f.is_file()) / 1e6
        mlflow.log_metric("saved_model_mb", size_mb)
        summary = metrics | {
            "saved_model_mb": round(size_mb, 1),
            "version": version,
            "mlflow_run_id": run.info.run_id,
            "tags": TAGS,
        }
        out = Path("ml/tagger/results.json")
        out.write_text(json.dumps(summary, indent=2) + "\n")
        print(f"exported {export_dir} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()

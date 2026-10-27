"""Package a trained tagger for TF Serving.

train.py writes a plain SavedModel that takes 224x224 uint8 pixels. This wraps it so
the default signature takes JPEG bytes instead: the worker sends each thumbnail as-is
(~20 KB base64) rather than ~600 KB of JSON numbers, and resizing happens in the graph.
The raw-pixel signature stays available as "pixels". tags.json goes next to the model
so the backend can check the output order matches its tag names.

    ml/.venv/bin/python ml/tagger/export.py models/tagger_build/<version> --out models/tagger
"""

import argparse
import json
import shutil
from pathlib import Path

import tensorflow as tf

SIZE = 224


class Tagger(tf.Module):
    def __init__(self, raw):
        super().__init__()
        self.raw = raw

    @tf.function(input_signature=[tf.TensorSpec([None], tf.string, name="image_bytes")])
    def from_jpeg(self, image_bytes):
        def decode(b):
            img = tf.io.decode_image(b, channels=3, expand_animations=False)
            # squash to 224x224 like training did (PIL bilinear ~ antialiased bilinear)
            img = tf.image.resize(img, (SIZE, SIZE), method="bilinear", antialias=True)
            return tf.cast(tf.clip_by_value(tf.round(img), 0, 255), tf.uint8)

        pixels = tf.map_fn(decode, image_bytes, fn_output_signature=tf.uint8)
        return {"tags": self.raw.signatures["serving_default"](image=pixels)["tags"]}

    @tf.function(input_signature=[tf.TensorSpec([None, SIZE, SIZE, 3], tf.uint8, name="image")])
    def from_pixels(self, image):
        return {"tags": self.raw.signatures["serving_default"](image=image)["tags"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("raw", type=Path, help="SavedModel written by train.py")
    ap.add_argument("--out", type=Path, default=Path("models/tagger"))
    ap.add_argument("--results", type=Path, default=Path("ml/tagger/results.json"))
    args = ap.parse_args()

    tags = json.loads(args.results.read_text())["tags"]
    module = Tagger(tf.saved_model.load(str(args.raw)))
    dst = args.out / args.raw.name  # keep the version number
    if dst.exists():
        shutil.rmtree(dst)
    tf.saved_model.save(
        module,
        str(dst),
        signatures={"serving_default": module.from_jpeg, "pixels": module.from_pixels},
    )
    (dst / "tags.json").write_text(json.dumps(tags) + "\n")
    print(f"wrote {dst}")


if __name__ == "__main__":
    main()

"""Convert the served tagger to ONNX so the backend can run it without TF Serving.

TF Serving only ships x86 images, so on ARM hosts (and anywhere TAGGER_URL is unset)
the worker runs this copy with onnxruntime instead. Same weights, converted from the
SavedModel's "pixels" signature (224x224 uint8 in, tag probabilities out). The tag
order and model version go in the file's metadata so the backend can check them.

    ml/.venv/bin/python ml/tagger/export_onnx.py
"""

import argparse
import subprocess
import sys
from pathlib import Path

import onnx


def latest(root: Path) -> Path:
    versions = sorted((p for p in root.glob("*") if p.name.isdigit()), key=lambda p: int(p.name))
    if not versions:
        raise SystemExit(f"no tagger under {root}, run scripts/get_models.sh")
    return versions[-1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", type=Path, default=Path("models/tagger"))
    ap.add_argument("--out", type=Path, default=Path("backend/lecturelens/assets/tagger.onnx"))
    args = ap.parse_args()

    src = latest(args.models)
    cmd = [sys.executable, "-m", "tf2onnx.convert", "--saved-model", str(src)]
    cmd += ["--signature_def", "pixels", "--opset", "17", "--output", str(args.out)]
    subprocess.run(cmd, check=True)
    model = onnx.load(str(args.out))
    model.metadata_props.add(key="tags", value=(src / "tags.json").read_text().strip())
    model.metadata_props.add(key="version", value=src.name)
    onnx.save(model, str(args.out))
    print(f"wrote {args.out} from tagger version {src.name}")


if __name__ == "__main__":
    main()

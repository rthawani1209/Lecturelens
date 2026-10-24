"""Download the pretrained models LectureLens builds on and export them for CPU inference.

  whisper/   faster-whisper base.en (CTranslate2, int8) for speech to text
  minilm/    all-MiniLM-L6-v2 as ONNX + tokenizer, 384-d sentence embeddings
  clip/      CLIP ViT-B/32 split into image and text ONNX graphs, 512-d shared space

Runs in the data-bundle GitHub workflow (needs Hugging Face + torch). The API and
workers only need onnxruntime afterwards, which keeps torch out of the images.

  python scripts/fetch_models.py --out models
"""

import argparse
import shutil
from pathlib import Path

import numpy as np

WHISPER_REPO = "Systran/faster-whisper-base.en"
MINILM_REPO = "sentence-transformers/all-MiniLM-L6-v2"
CLIP_REPO = "openai/clip-vit-base-patch32"


def fetch_whisper(out: Path) -> None:
    from huggingface_hub import snapshot_download

    snapshot_download(WHISPER_REPO, local_dir=out / "whisper")


def fetch_minilm(out: Path) -> None:
    from huggingface_hub import snapshot_download

    dst = out / "minilm"
    snapshot_download(
        MINILM_REPO,
        local_dir=dst,
        allow_patterns=["onnx/model.onnx", "tokenizer.json", "config.json"],
    )
    shutil.move(dst / "onnx" / "model.onnx", dst / "model.onnx")
    shutil.rmtree(dst / "onnx")


def export_clip(out: Path) -> None:
    import torch
    from huggingface_hub import hf_hub_download
    from transformers import CLIPModel

    dst = out / "clip"
    dst.mkdir(parents=True, exist_ok=True)
    model = CLIPModel.from_pretrained(CLIP_REPO).eval()

    class Image(torch.nn.Module):
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, pixel_values):
            return self.m.get_image_features(pixel_values=pixel_values)

    class Text(torch.nn.Module):
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, input_ids, attention_mask):
            return self.m.get_text_features(input_ids=input_ids, attention_mask=attention_mask)

    pixels = torch.randn(2, 3, 224, 224)
    ids = torch.randint(0, 49407, (2, 77))
    mask = torch.ones(2, 77, dtype=torch.long)
    with torch.no_grad():
        torch.onnx.export(
            Image(model),
            (pixels,),
            dst / "image.onnx",
            dynamo=False,
            opset_version=17,
            input_names=["pixel_values"],
            output_names=["embeds"],
            dynamic_axes={"pixel_values": {0: "batch"}, "embeds": {0: "batch"}},
        )
        torch.onnx.export(
            Text(model),
            (ids, mask),
            dst / "text.onnx",
            dynamo=False,
            opset_version=17,
            input_names=["input_ids", "attention_mask"],
            output_names=["embeds"],
            dynamic_axes={
                "input_ids": {0: "batch"},
                "attention_mask": {0: "batch"},
                "embeds": {0: "batch"},
            },
        )
        ref_img = Image(model)(pixels).numpy()
        ref_txt = Text(model)(ids, mask).numpy()
    shutil.copy(hf_hub_download(CLIP_REPO, "tokenizer.json"), dst / "tokenizer.json")

    # make sure the exported graphs match torch before we ship them
    import onnxruntime as ort

    img_sess = ort.InferenceSession(str(dst / "image.onnx"))
    img = img_sess.run(None, {"pixel_values": pixels.numpy()})[0]
    txt = ort.InferenceSession(str(dst / "text.onnx")).run(
        None, {"input_ids": ids.numpy(), "attention_mask": mask.numpy()}
    )[0]
    print("clip image max diff", np.abs(img - ref_img).max())
    print("clip text max diff", np.abs(txt - ref_txt).max())
    assert np.allclose(img, ref_img, atol=1e-3) and np.allclose(txt, ref_txt, atol=1e-3)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("models"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    fetch_whisper(args.out)
    fetch_minilm(args.out)
    export_clip(args.out)
    for p in sorted(args.out.rglob("*")):
        if p.is_file():
            print(f"{p.stat().st_size / 1e6:8.1f} MB  {p}")


if __name__ == "__main__":
    main()

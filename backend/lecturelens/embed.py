"""Turn text and images into vectors with ONNX Runtime (no torch at serve time).

TextEmbedder: all-MiniLM-L6-v2, 384-d. Good at "these two sentences mean the same".
ClipEmbedder: CLIP ViT-B/32, 512-d. Puts images and short text in one space, so
"the slide with the big-O table" can find a frame.
"""

from functools import lru_cache
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image
from tokenizers import Tokenizer

from .config import get_settings

# CLIP's training-time image normalisation
CLIP_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
CLIP_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)
CLIP_CONTEXT = 77
CLIP_EOT = 49407


def _session(path: Path) -> ort.InferenceSession:
    opts = ort.SessionOptions()
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])


def _l2(x: np.ndarray) -> np.ndarray:
    return x / np.maximum(np.linalg.norm(x, axis=-1, keepdims=True), 1e-12)


class TextEmbedder:
    dim = 384

    def __init__(self, model_dir: Path, max_tokens: int = 256):
        self.session = _session(model_dir / "model.onnx")
        self.tok = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tok.enable_truncation(max_tokens)
        self.tok.enable_padding(pad_id=0, pad_token="[PAD]")  # pad to longest in batch

    def embed(self, texts: list[str], batch: int = 32) -> np.ndarray:
        out = []
        for i in range(0, len(texts), batch):
            enc = self.tok.encode_batch(texts[i : i + batch])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            hidden = self.session.run(
                None,
                {"input_ids": ids, "attention_mask": mask, "token_type_ids": np.zeros_like(ids)},
            )[0]
            # mean over real tokens only, like sentence-transformers does
            m = mask[..., None].astype(np.float32)
            out.append(_l2((hidden * m).sum(1) / np.maximum(m.sum(1), 1e-9)))
        return np.concatenate(out) if out else np.zeros((0, self.dim), np.float32)


def clip_preprocess(img: Image.Image, size: int = 224) -> np.ndarray:
    """Resize shortest side to 224 (bicubic), center crop, normalise -> (3, 224, 224)."""
    img = img.convert("RGB")
    w, h = img.size
    scale = size / min(w, h)
    img = img.resize(
        (max(size, round(w * scale)), max(size, round(h * scale))), Image.Resampling.BICUBIC
    )
    w, h = img.size
    left, top = (w - size) // 2, (h - size) // 2
    arr = np.asarray(img.crop((left, top, left + size, top + size)), dtype=np.float32) / 255.0
    return ((arr - CLIP_MEAN) / CLIP_STD).transpose(2, 0, 1)


class ClipEmbedder:
    dim = 512

    def __init__(self, model_dir: Path):
        self.image = _session(model_dir / "image.onnx")
        self.text = _session(model_dir / "text.onnx")
        self.tok = Tokenizer.from_file(str(model_dir / "tokenizer.json"))

    def embed_images(self, images: list[Image.Image | Path], batch: int = 16) -> np.ndarray:
        out = []
        for i in range(0, len(images), batch):
            chunk = [Image.open(x) if isinstance(x, Path) else x for x in images[i : i + batch]]
            pixels = np.stack([clip_preprocess(im) for im in chunk])
            out.append(_l2(self.image.run(None, {"pixel_values": pixels})[0]))
        return np.concatenate(out) if out else np.zeros((0, self.dim), np.float32)

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        ids = np.full((len(texts), CLIP_CONTEXT), CLIP_EOT, dtype=np.int64)
        mask = np.zeros_like(ids)
        for row, text in enumerate(texts):
            toks = self.tok.encode(text.lower()).ids[:CLIP_CONTEXT]
            toks[-1] = CLIP_EOT  # keep the end token if we had to truncate
            ids[row, : len(toks)] = toks
            mask[row, : len(toks)] = 1
        if not texts:
            return np.zeros((0, self.dim), np.float32)
        return _l2(self.text.run(None, {"input_ids": ids, "attention_mask": mask})[0])


@lru_cache(maxsize=1)
def text_embedder() -> TextEmbedder:
    return TextEmbedder(Path(get_settings().models_dir) / "minilm")


@lru_cache(maxsize=1)
def clip_embedder() -> ClipEmbedder:
    return ClipEmbedder(Path(get_settings().models_dir) / "clip")

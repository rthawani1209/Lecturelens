"""Speech to text with faster-whisper (CTranslate2, int8 on CPU)."""

import wave
from functools import lru_cache
from pathlib import Path

import numpy as np

from .chunk import Sentence


@lru_cache(maxsize=1)
def _model(model_dir: str):
    from faster_whisper import WhisperModel

    return WhisperModel(model_dir, device="cpu", compute_type="int8")


def load_wav(path: Path) -> np.ndarray:
    """16 kHz mono PCM -> float32 in [-1, 1]. We already made this wav with ffmpeg, so we
    skip faster-whisper's own PyAV decoding (one less native dependency to break)."""
    with wave.open(str(path)) as w:
        if w.getframerate() != 16000 or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError("expected 16 kHz mono 16-bit wav")
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return pcm.astype(np.float32) / 32768.0


def transcribe(
    wav: Path, model_dir: Path, terms: list[str] | None = None, on_progress=None
) -> list[Sentence]:
    """Course terms ("Dijkstra", "Bellman-Ford") are passed as hotwords so whisper
    prefers those spellings over "dyke stra"."""
    model = _model(str(model_dir))
    segments, info = model.transcribe(
        load_wav(wav),
        language="en",
        beam_size=1,
        vad_filter=True,
        hotwords=", ".join(terms) if terms else None,
    )
    out = []
    for seg in segments:
        out.append(Sentence(float(seg.start), float(seg.end), seg.text.strip()))
        if on_progress and info.duration:
            on_progress(min(seg.end / info.duration, 1.0))
    return out

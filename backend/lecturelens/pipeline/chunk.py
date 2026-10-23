"""Turn whisper's sentence-level segments into overlapping ~30 s search windows.

Single sentences are too short to match a question ("why does it need positive
weights?"), whole lectures too long to point at a moment. Overlapping windows mean
an idea that straddles a boundary still lands whole in at least one window.
"""

from dataclasses import dataclass


@dataclass
class Sentence:
    start_s: float
    end_s: float
    text: str


@dataclass
class Window:
    start_s: float
    end_s: float
    text: str


def windows(
    sentences: list[Sentence], size_s: float = 30.0, stride_s: float = 15.0
) -> list[Window]:
    if not sentences:
        return []
    out: list[Window] = []
    end = sentences[-1].end_s
    t = sentences[0].start_s
    while True:
        inside = [s for s in sentences if s.start_s < t + size_s and s.end_s > t]
        if inside:
            w = Window(
                inside[0].start_s, inside[-1].end_s, " ".join(s.text.strip() for s in inside)
            )
            if not out or (w.start_s, w.end_s) != (out[-1].start_s, out[-1].end_s):
                out.append(w)
        if t + size_s >= end:
            break
        t += stride_s
    return out

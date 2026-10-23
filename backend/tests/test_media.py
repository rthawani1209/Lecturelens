import shutil

import pytest

from lecturelens.pipeline.dedup import dedupe, signature
from lecturelens.pipeline.media import MediaError, extract_audio, keyframes, probe
from lecturelens.pipeline.ocr import clean, ocr


def test_probe_reports_streams(lecture_fixture):
    video, truth = lecture_fixture
    info = probe(video)
    assert info["has_video"] and info["has_audio"]
    assert info["duration_s"] == pytest.approx(truth["duration_s"], abs=0.5)


def test_probe_rejects_non_video(tmp_path):
    fake = tmp_path / "lecture.mp4"
    fake.write_text("not a video")
    with pytest.raises(MediaError):
        probe(fake)


def test_extract_audio_is_16k_mono(lecture_fixture, tmp_path):
    import wave

    video, truth = lecture_fixture
    with wave.open(str(extract_audio(video, tmp_path / "a.wav"))) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        assert w.getnframes() / 16000 == pytest.approx(truth["duration_s"], abs=0.5)


def test_keyframes_catch_every_slide_change(lecture_fixture, tmp_path):
    video, truth = lecture_fixture
    shots = keyframes(video, tmp_path / "frames")
    kept = [shots[i] for i in dedupe([signature(s.path) for s in shots])]
    starts = [s["start_s"] for s in truth["slides"]]
    assert len(kept) == len(starts)
    for shot, start in zip(kept, starts, strict=True):
        assert shot.t_s == pytest.approx(start, abs=0.5)


@pytest.mark.skipif(not shutil.which("tesseract"), reason="needs tesseract")
def test_ocr_reads_slide_titles(lecture_fixture, tmp_path):
    video, truth = lecture_fixture
    shots = keyframes(video, tmp_path / "frames")
    text = ocr(shots[0].path)
    assert "Graph Search" in text
    assert "Breadth first search" in text


def test_ocr_clean_drops_junk_lines():
    assert clean("  Running   Time \n|| ~\n a\nO(E log V)") == "Running Time\nO(E log V)"

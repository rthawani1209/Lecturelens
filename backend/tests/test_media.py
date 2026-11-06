import re
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


def test_probe_measures_a_video_whose_header_has_no_length(tmp_path):
    # what a browser's MediaRecorder or a piped ffmpeg writes: no duration in the header
    import subprocess

    enc = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=d=7:s=320x240:r=10",
            "-c:v",
            "libvpx-vp9",
            "-deadline",
            "realtime",
            "-cpu-used",
            "8",
            "-f",
            "webm",
            "-",
        ],
        capture_output=True,
        check=True,
    )
    piped = tmp_path / "recorded.webm"
    piped.write_bytes(enc.stdout)
    assert probe(piped)["duration_s"] == pytest.approx(7, abs=0.5)


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


def test_ocr_timeout_skips_the_frame(monkeypatch, tmp_path):
    import subprocess

    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])

    monkeypatch.setattr(subprocess, "run", slow)
    assert ocr(tmp_path / "frame.jpg") == ""


@pytest.mark.skipif(not shutil.which("tesseract"), reason="needs tesseract")
@pytest.mark.parametrize("bg,fg", [("#1E1E1E", "#D4D4D4"), ("#FFFFFF", "#24292E")])
def test_ocr_reads_a_screen_recording_of_code(bg, fg, tmp_path):
    import inspect
    import textwrap

    from PIL import Image, ImageDraw, ImageFont

    # 18 px code in an editor on a 1080p screen, scaled to 1280 wide like every frame
    code = textwrap.dedent(inspect.getsource(dedupe)).splitlines()
    try:
        font = ImageFont.truetype("DejaVuSansMono.ttf", 18)
    except OSError:
        pytest.skip("needs the DejaVu fonts")
    img = Image.new("RGB", (1920, 1080), bg)
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(code):
        draw.text((60, 40 + i * 26), line, fill=fg, font=font)
    path = tmp_path / "code.jpg"
    img.resize((1280, 720)).save(path, quality=80)

    # the names in the code are what people search for; brackets and commas matter less
    names = set(re.findall(r"[A-Za-z_]{3,}", "\n".join(code)))
    read = set(re.findall(r"[A-Za-z_]{3,}", ocr(path)))
    assert len(names & read) / len(names) > 0.9, names - read

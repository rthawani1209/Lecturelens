"""The kinds of video people actually upload, each through the whole pipeline."""

import subprocess

import pytest

from lecturelens.pipeline import stages
from lecturelens.pipeline.media import probe

pytestmark = pytest.mark.db

X264 = ["-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac"]
VARIANTS = {
    # name: (file extension, ffmpeg input options, output options)
    "mov": (".mov", [], ["-c", "copy"]),
    "m4v": (".m4v", [], ["-c", "copy", "-f", "mp4"]),
    "mkv": (".mkv", [], ["-c", "copy"]),
    "mkv with opus audio": (".mkv", [], ["-c:v", "copy", "-c:a", "libopus"]),
    "webm": (
        ".webm",
        [],
        ["-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8", "-c:a", "libopus"],
    ),
    # a phone held upright, filming the screen: the slide sits in the middle
    "portrait phone video": (
        ".mp4",
        [],
        ["-vf", "scale=720:-2,pad=720:1280:(ow-iw)/2:(oh-ih)/2", *X264],
    ),
    "rotated by metadata": (".mp4", ["-display_rotation:v:0", "90"], ["-c", "copy"]),
    "low resolution": (".mp4", [], ["-vf", "scale=320:180", *X264]),
    "1080p at 60 fps": (".mp4", [], ["-vf", "scale=1920:1080,fps=60", *X264]),
}
# sideways slides still become frames, but nobody expects OCR to read them
UPRIGHT = set(VARIANTS) - {"rotated by metadata"}


def _ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *map(str, args)], check=True)


@pytest.mark.parametrize("name", VARIANTS)
def test_format_goes_through_the_pipeline(
    name, db, lecture, lecture_fixture, storage, fake_whisper, models_env, tmp_path
):
    lid, truth = lecture
    ext, pre, post = VARIANTS[name]
    video = tmp_path / f"in{ext}"
    _ffmpeg(*pre, "-i", lecture_fixture[0], *post, video)
    key = f"lectures/{lid}/source{ext}"
    storage.put_file(key, video)
    db.execute("UPDATE lectures SET storage_key = %s WHERE id = %s", (key, lid))

    stages.run_pipeline(lid)

    status, duration, stored = db.execute(
        "SELECT status, duration_s, storage_key FROM lectures WHERE id = %s", (lid,)
    ).fetchone()
    assert status == "ready"
    assert duration == pytest.approx(truth["duration_s"], abs=1)
    frames = db.execute(
        "SELECT ocr_text FROM frames WHERE lecture_id = %s ORDER BY t_s", (lid,)
    ).fetchall()
    assert len(frames) == len(truth["slides"])
    if name in UPRIGHT:
        # every slide, the code one included, can be read
        assert all(text for (text,) in frames)
        assert "Graph Search" in frames[0][0]
    # whatever came in, the player gets a container browsers can play
    assert stored.rsplit(".", 1)[1] in {"mp4", "m4v", "mov", "webm"}
    if ext == ".mkv":
        assert stored.endswith("/source.mp4") and not storage.exists(key)
        info = probe(storage.path(stored))
        assert (info["video_codec"], info["audio_codec"]) == ("h264", "aac")


def test_a_few_seconds_of_video(
    db, lecture, lecture_fixture, storage, fake_whisper, models_env, tmp_path
):
    lid, _ = lecture
    clip = tmp_path / "short.mp4"
    _ffmpeg("-i", lecture_fixture[0], "-t", "2", "-c", "copy", clip)
    storage.put_file("uploads/x.mp4", clip)
    stages.run_pipeline(lid)
    assert db.execute("SELECT status FROM lectures WHERE id = %s", (lid,)).fetchone()[0] == "ready"
    n = db.execute("SELECT count(*) FROM frames WHERE lecture_id = %s", (lid,)).fetchone()[0]
    assert n >= 1


def test_video_no_browser_can_play_fails_with_a_plain_reason(
    db, lecture, lecture_fixture, storage, tmp_path
):
    lid, _ = lecture
    video = tmp_path / "old.mkv"
    _ffmpeg("-i", lecture_fixture[0], "-t", "3", "-c:v", "mpeg2video", "-c:a", "mp2", video)
    key = f"lectures/{lid}/source.mkv"
    storage.put_file(key, video)
    db.execute("UPDATE lectures SET storage_key = %s WHERE id = %s", (key, lid))
    with pytest.raises(Exception, match="convert it to MP4"):
        stages.run_stage(lid, "probe")

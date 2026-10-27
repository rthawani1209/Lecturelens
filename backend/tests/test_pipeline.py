"""End-to-end pipeline on the synthetic lecture, against a real Postgres."""

import pytest

from lecturelens.pipeline import stages
from tests.conftest import MODELS

pytestmark = pytest.mark.db


def _count(db, table, lid):
    return db.execute(f"SELECT count(*) FROM {table} WHERE lecture_id = %s", (lid,)).fetchone()[0]


def test_full_pipeline(db, lecture, fake_whisper, models_env):
    lid, truth = lecture
    stages.run_pipeline(lid)

    status, duration = db.execute(
        "SELECT status, duration_s FROM lectures WHERE id = %s", (lid,)
    ).fetchone()
    assert status == "ready"
    assert duration == pytest.approx(truth["duration_s"], abs=0.5)

    frames = db.execute(
        "SELECT t_s, ocr_text FROM frames WHERE lecture_id = %s ORDER BY t_s", (lid,)
    ).fetchall()
    assert len(frames) == len(truth["slides"])
    assert "Graph Search" in frames[0][1]
    assert "Running Time" in frames[-1][1]

    assert _count(db, "transcript_lines", lid) == len(truth["slides"])
    hits = db.execute(
        "SELECT start_s FROM segments WHERE lecture_id = %s"
        " AND tsv @@ websearch_to_tsquery('english', 'smallest estimate')",
        (lid,),
    ).fetchall()
    assert hits, "keyword search should find the Dijkstra sentence"
    missing = db.execute(
        "SELECT count(*) FROM segments WHERE lecture_id = %s AND text_emb IS NULL", (lid,)
    ).fetchone()[0]
    assert missing == 0
    assert (
        db.execute(
            "SELECT count(*) FROM frames WHERE lecture_id = %s AND clip_emb IS NULL", (lid,)
        ).fetchone()[0]
        == 0
    )
    # without TF Serving the CLIP probe tags frames; every frame gets a tag and scores
    tagged = db.execute(
        "SELECT tag, tag_scores FROM frames WHERE lecture_id = %s ORDER BY t_s", (lid,)
    ).fetchall()
    assert all(tag and abs(sum(scores.values()) - 1) < 1e-3 for tag, scores in tagged)


def test_tagging_survives_tf_serving_being_down(db, lecture, fake_whisper, models_env, monkeypatch):
    lid, _ = lecture
    stages.run_pipeline(lid)
    db.execute("UPDATE frames SET tag = NULL, tag_scores = NULL")
    monkeypatch.setenv("TAGGER_URL", "http://127.0.0.1:9")  # nothing listens here
    from lecturelens.config import get_settings

    get_settings.cache_clear()
    stages.run_stage(lid, "tag")
    get_settings.cache_clear()
    assert _count(db, "frames", lid) > 0
    untagged = db.execute(
        "SELECT count(*) FROM frames WHERE lecture_id = %s AND tag IS NULL", (lid,)
    ).fetchone()[0]
    assert untagged == 0
    status = db.execute(
        "SELECT status FROM jobs WHERE lecture_id = %s AND stage = 'tag'", (lid,)
    ).fetchone()[0]
    assert status == "done"


def test_stages_are_idempotent(db, lecture, fake_whisper, models_env):
    lid, _ = lecture
    stages.run_pipeline(lid)
    before = {t: _count(db, t, lid) for t in ("frames", "segments", "transcript_lines")}
    stages.run_stage(lid, "frames")
    stages.run_stage(lid, "transcribe")
    after = {t: _count(db, t, lid) for t in ("frames", "segments", "transcript_lines")}
    assert before == after


def test_crash_mid_pipeline_resumes_without_redoing_work(
    db, lecture, fake_whisper, models_env, monkeypatch
):
    lid, _ = lecture
    real_ocr = stages.stage_ocr

    def boom(*a, **k):
        raise RuntimeError("worker died")

    monkeypatch.setattr(
        stages, "STAGES", [(n, boom if n == "ocr" else f) for n, f in stages.STAGES]
    )
    with pytest.raises(RuntimeError):
        stages.run_pipeline(lid)
    status, error = db.execute(
        "SELECT status, error FROM jobs WHERE lecture_id = %s AND stage = 'ocr'", (lid,)
    ).fetchone()
    assert status == "failed" and "worker died" in error

    # the retry: earlier stages are skipped, only ocr runs again
    monkeypatch.setattr(
        stages, "STAGES", [(n, real_ocr if n == "ocr" else f) for n, f in stages.STAGES]
    )
    stages.run_pipeline(lid)
    attempts = dict(
        db.execute("SELECT stage, attempts FROM jobs WHERE lecture_id = %s", (lid,)).fetchall()
    )
    assert attempts == {
        "fetch": 1,
        "probe": 1,
        "audio": 1,
        "transcribe": 1,
        "frames": 1,
        "ocr": 2,
        "embed_text": 1,
        "embed_frames": 1,
        "tag": 1,
    }
    assert len(fake_whisper) == 1
    assert db.execute("SELECT status FROM lectures WHERE id = %s", (lid,)).fetchone()[0] == "ready"


def test_rejects_file_without_audio(db, lecture, storage, tmp_path):
    import subprocess

    lid, _ = lecture
    silent = tmp_path / "silent.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=d=2", str(silent)], check=True
    )
    storage.put_file("uploads/x.mp4", silent)
    with pytest.raises(Exception, match="audio"):
        stages.run_stage(lid, "probe")


@pytest.mark.skipif(not (MODELS / "whisper").exists(), reason="whisper model not downloaded")
def test_real_whisper_and_course_vocabulary(lecture_fixture, tmp_path):
    from lecturelens.pipeline.media import extract_audio
    from lecturelens.pipeline.transcribe import transcribe

    video, _ = lecture_fixture
    wav = extract_audio(video, tmp_path / "a.wav")

    def heard(terms=None):
        return " ".join(s.text for s in transcribe(wav, MODELS / "whisper", terms)).lower()

    plain = heard()
    assert "smallest estimate" in plain
    assert "breadth first search" in plain
    # espeak's robot voice says "Dijkstra" badly; the course vocabulary fixes it
    tuned = heard(["Dijkstra", "graph search", "binary heap"])
    for term in ("dijkstra", "graph search", "binary heap"):
        assert term in tuned

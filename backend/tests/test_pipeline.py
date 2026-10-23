"""End-to-end pipeline on the synthetic lecture, against a real Postgres."""

from pathlib import Path

import pytest

from lecturelens.pipeline import stages
from lecturelens.pipeline.chunk import Sentence
from lecturelens.storage import LocalStorage, set_storage

pytestmark = pytest.mark.db

MODELS = Path(__file__).resolve().parents[2] / "models"


@pytest.fixture
def storage(tmp_path):
    s = LocalStorage(tmp_path / "blobs")
    set_storage(s)
    yield s
    set_storage(None)


@pytest.fixture
def lecture(db, storage, lecture_fixture):
    video, truth = lecture_fixture
    gid = db.execute("INSERT INTO groups (name) VALUES ('g') RETURNING id").fetchone()[0]
    cid = db.execute(
        "INSERT INTO courses (group_id, title) VALUES (%s, 'Algorithms') RETURNING id", (gid,)
    ).fetchone()[0]
    lid = db.execute(
        "INSERT INTO lectures (course_id, title, storage_key, status)"
        " VALUES (%s, 'Shortest paths', 'uploads/x.mp4', 'queued') RETURNING id",
        (cid,),
    ).fetchone()[0]
    storage.put_file("uploads/x.mp4", video)
    return lid, truth


@pytest.fixture
def fake_whisper(monkeypatch, lecture_fixture):
    """Stand-in for whisper that 'hears' exactly what the fixture narrated."""
    _, truth = lecture_fixture
    calls = []

    def fake(wav, model_dir, terms=None, on_progress=None):
        calls.append(wav)
        return [Sentence(s["start_s"], s["end_s"] - 1, s["spoken"]) for s in truth["slides"]]

    monkeypatch.setattr(stages, "transcribe", fake)
    return calls


def _count(db, table, lid):
    return db.execute(f"SELECT count(*) FROM {table} WHERE lecture_id = %s", (lid,)).fetchone()[0]


def test_full_pipeline(db, lecture, fake_whisper):
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


def test_stages_are_idempotent(db, lecture, fake_whisper):
    lid, _ = lecture
    stages.run_pipeline(lid)
    before = {t: _count(db, t, lid) for t in ("frames", "segments", "transcript_lines")}
    stages.run_stage(lid, "frames")
    stages.run_stage(lid, "transcribe")
    after = {t: _count(db, t, lid) for t in ("frames", "segments", "transcript_lines")}
    assert before == after


def test_crash_mid_pipeline_resumes_without_redoing_work(db, lecture, fake_whisper, monkeypatch):
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
    assert attempts == {"probe": 1, "audio": 1, "transcribe": 1, "frames": 1, "ocr": 2}
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

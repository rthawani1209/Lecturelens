import os
from pathlib import Path

import psycopg
import pytest

from lecturelens.db.migrate import migrate
from lecturelens.pipeline import stages
from lecturelens.pipeline.chunk import Sentence
from lecturelens.storage import LocalStorage, set_storage

MODELS = Path(__file__).resolve().parents[2] / "models"
HAVE_MODELS = (MODELS / "minilm").exists() and (MODELS / "clip").exists()

TEST_DB = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://lecturelens:lecturelens@localhost:5432/lecturelens_test"
)


def _db_available() -> bool:
    try:
        psycopg.connect(TEST_DB, connect_timeout=2).close()
        return True
    except psycopg.OperationalError:
        return False


@pytest.fixture(scope="session")
def database_url():
    if not _db_available():
        pytest.skip("Postgres not available (set TEST_DATABASE_URL)")
    with psycopg.connect(TEST_DB, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    migrate(TEST_DB)
    os.environ["DATABASE_URL"] = TEST_DB
    from lecturelens.config import get_settings

    get_settings.cache_clear()
    return TEST_DB


@pytest.fixture
def db(database_url):
    with psycopg.connect(database_url, autocommit=True) as conn:
        yield conn
        conn.execute("TRUNCATE users, groups, courses CASCADE")


@pytest.fixture(scope="session")
def lecture_fixture(tmp_path_factory):
    """A ~28s synthetic lecture with known slides and narration (see fixtures/lecture.py)."""
    import shutil

    if not (shutil.which("ffmpeg") and shutil.which("espeak-ng")):
        pytest.skip("needs ffmpeg and espeak-ng")
    from tests.fixtures.lecture import build

    out = tmp_path_factory.mktemp("lecture")
    truth = build(out)
    return out / "lecture.mp4", truth


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


@pytest.fixture
def models_env(monkeypatch):
    if not HAVE_MODELS:
        pytest.skip("models not downloaded (scripts/get_models.sh)")
    monkeypatch.setenv("MODELS_DIR", str(MODELS))
    from lecturelens.config import get_settings

    get_settings.cache_clear()
    yield MODELS
    get_settings.cache_clear()

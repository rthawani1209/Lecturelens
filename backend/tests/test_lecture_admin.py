"""What happens to a bad upload: it fails fast, says why in plain words, and can be
retried or deleted by its owner."""

import pytest

from lecturelens.worker import process_lecture

pytestmark = pytest.mark.db


@pytest.fixture
def owned(client, sign_in, storage, monkeypatch, db):
    queued = []
    monkeypatch.setattr("lecturelens.queue.enqueue", queued.append)
    sign_in(client, "ada@example.com")
    course = client.post("/courses", json={"title": "Algorithms"}).json()["id"]
    lid = db.execute(
        "INSERT INTO lectures (course_id, title, storage_key, status)"
        " VALUES (%s, 'Broken', 'tmp-key', 'queued') RETURNING id",
        (course,),
    ).fetchone()[0]
    db.execute(
        "UPDATE lectures SET storage_key = %s WHERE id = %s", (f"lectures/{lid}/source.mp4", lid)
    )
    return client, lid, queued


def test_corrupt_video_fails_fast_with_a_plain_error(owned, storage, tmp_path):
    client, lid, _ = owned
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"garbage" * 1000)  # looks like mp4, isn't
    storage.put_file(f"lectures/{lid}/source.mp4", bad)

    process_lecture.apply(args=[str(lid)])  # no retries for a file that can't work

    body = client.get(f"/lectures/{lid}").json()
    assert body["status"] == "failed"
    failed = [s for s in body["stages"] if s["status"] == "failed"]
    assert [s["error"] for s in failed] == ["This file isn't a playable video."]
    assert "/tmp" not in str(body) and "ffprobe" not in str(body)


def test_retry_requeues_only_failed_lectures(owned, db):
    client, lid, queued = owned
    assert client.post(f"/lectures/{lid}/retry").status_code == 409
    db.execute("UPDATE lectures SET status = 'failed' WHERE id = %s", (lid,))
    db.execute(
        "INSERT INTO jobs (lecture_id, stage, status, error) VALUES (%s, 'probe', 'failed', 'x')",
        (lid,),
    )
    body = client.post(f"/lectures/{lid}/retry").json()
    assert body["status"] == "queued" and queued == [lid]
    assert (
        db.execute("SELECT status FROM jobs WHERE lecture_id = %s", (lid,)).fetchone()[0]
        == "pending"
    )


def test_only_the_owner_can_delete(owned, db, storage, tmp_path, sign_in):
    from fastapi.testclient import TestClient

    from lecturelens.api.main import create_app

    client, lid, _ = owned
    (tmp_path / "f.jpg").write_bytes(b"jpg")
    storage.put_file(f"lectures/{lid}/frames/f.jpg", tmp_path / "f.jpg")

    bob = TestClient(create_app())
    sign_in(bob, "bob@example.com")
    assert bob.delete(f"/lectures/{lid}").status_code == 404
    assert bob.post(f"/lectures/{lid}/retry").status_code == 404

    assert client.delete(f"/lectures/{lid}").status_code == 204
    assert db.execute("SELECT count(*) FROM lectures WHERE id = %s", (lid,)).fetchone()[0] == 0
    assert not storage.exists(f"lectures/{lid}/frames/f.jpg")
    assert client.get(f"/lectures/{lid}").status_code == 404


def test_a_lecture_deleted_mid_processing_isnt_retried(owned, db, storage, monkeypatch):
    from lecturelens.pipeline import stages

    client, lid, _ = owned

    def deleted_meanwhile(*args):
        client.delete(f"/lectures/{lid}")
        storage.put_file(f"lectures/{lid}/frames/1.jpg", __file__)  # written after the delete
        raise RuntimeError("lecture vanished")

    monkeypatch.setattr(stages, "run_pipeline", deleted_meanwhile)
    monkeypatch.setattr("lecturelens.worker.run_pipeline", deleted_meanwhile)
    result = process_lecture.apply(args=[str(lid)])
    assert result.successful()  # no retry, no error
    assert not storage.exists(f"lectures/{lid}/frames/1.jpg")


def test_a_lecture_stuck_for_an_hour_can_be_retried_once(owned, db):
    client, lid, queued = owned
    db.execute("UPDATE lectures SET status = 'processing' WHERE id = %s", (lid,))
    db.execute(
        "INSERT INTO jobs (lecture_id, stage, status) VALUES (%s, 'transcribe', 'running')", (lid,)
    )
    assert client.post(f"/lectures/{lid}/retry").status_code == 409  # still moving
    db.execute("UPDATE lectures SET created_at = now() - interval '2 hours' WHERE id = %s", (lid,))
    db.execute("UPDATE jobs SET updated_at = now() - interval '2 hours'")
    assert client.post(f"/lectures/{lid}/retry").json()["status"] == "queued"
    assert client.post(f"/lectures/{lid}/retry").status_code == 409  # a second click
    assert queued == [lid]


def test_worker_start_requeues_unfinished_lectures(owned, db, monkeypatch):
    from lecturelens import worker

    _, lid, _ = owned
    sent = []
    monkeypatch.setattr(worker.process_lecture, "delay", sent.append)
    worker.requeue_interrupted()
    assert sent == [str(lid)]


def test_one_run_per_lecture_at_a_time(owned, monkeypatch):
    from lecturelens import worker

    _, lid, _ = owned
    runs = []

    def pipeline(x):
        # the same lecture queued again while this run holds it
        assert process_lecture.apply(args=[str(lid)]).successful()
        runs.append(x)

    monkeypatch.setattr(worker, "run_pipeline", pipeline)
    process_lecture.apply(args=[str(lid)])
    assert runs == [lid]

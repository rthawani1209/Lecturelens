import uuid

import pytest

from lecturelens import signing
from lecturelens.api.routes import lectures as lecture_routes
from lecturelens.pipeline import stages
from lecturelens.pipeline.fetch import youtube_id

pytestmark = pytest.mark.db


@pytest.fixture
def queued(monkeypatch):
    calls = []
    monkeypatch.setattr("lecturelens.queue.enqueue", calls.append)
    return calls


@pytest.fixture
def setup(client, sign_in, storage, queued, tmp_path, monkeypatch):
    from lecturelens.config import get_settings

    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "parts"))
    get_settings.cache_clear()
    sign_in(client, "ada@example.com")
    course = client.post("/courses", json={"title": "Algorithms"}).json()["id"]
    yield client, course
    get_settings.cache_clear()


MP4_HEAD = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2"


def _start(client, course, data: bytes, name="lecture.mp4"):
    r = client.post(
        f"/courses/{course}/lectures",
        json={"title": "Shortest paths", "filename": name, "size": len(data)},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _put(client, url, data, first, last, total):
    return client.put(
        url,
        content=data[first : last + 1],
        headers={"Content-Range": f"bytes {first}-{last}/{total}"},
    )


def test_chunked_upload_resumes_and_queues(setup, db, storage, queued):
    client, course = setup
    data = MP4_HEAD + bytes(range(256)) * 400  # ~100 KB
    up = _start(client, course, data)
    url, n = up["upload_url"], len(data)

    r = _put(client, url, data, 0, 39_999, n)
    assert r.status_code == 308 and r.headers["range"] == "bytes=0-39999"

    # the client lost track: a chunk from the wrong offset is refused, and it can ask
    assert _put(client, url, data, 60_000, 79_999, n).headers["range"] == "bytes=0-39999"
    status = client.put(url, headers={"Content-Range": f"bytes */{n}"})
    assert status.status_code == 308 and status.headers["range"] == "bytes=0-39999"

    assert _put(client, url, data, 40_000, n - 1, n).status_code == 201
    lec = db.execute("SELECT id, status, storage_key FROM lectures").fetchone()
    assert lec[1] == "queued"
    assert queued == [lec[0]]
    assert (storage.root / lec[2]).read_bytes() == data
    # finishing twice is harmless
    assert _put(client, url, data, 40_000, n - 1, n).status_code == 200
    assert len(queued) == 1


def test_same_video_twice_points_at_the_first_lecture(setup, db, queued):
    client, course = setup
    data = MP4_HEAD + b"same lecture" * 1000
    first = _start(client, course, data)
    r = _put(client, first["upload_url"], data, 0, len(data) - 1, len(data))
    assert r.status_code == 201 and r.json() == {
        "lecture_id": first["lecture_id"],
        "duplicate": False,
    }

    second = _start(client, course, data)
    r = _put(client, second["upload_url"], data, 0, len(data) - 1, len(data))
    assert r.status_code == 200
    assert r.json() == {"lecture_id": first["lecture_id"], "duplicate": True}
    assert db.execute("SELECT count(*) FROM lectures").fetchone()[0] == 1
    assert len(queued) == 1
    # a retried last chunk (reply lost) still gets the right answer
    r = _put(client, second["upload_url"], data, 0, len(data) - 1, len(data))
    assert r.json()["lecture_id"] == first["lecture_id"]

    # another course is a different place: it gets its own lecture
    other = client.post("/courses", json={"title": "Other"}).json()["id"]
    third = _start(client, other, data)
    r = _put(client, third["upload_url"], data, 0, len(data) - 1, len(data))
    assert r.status_code == 201 and r.json()["duplicate"] is False


def test_upload_link_must_be_signed_and_fresh(setup):
    client, course = setup
    up = _start(client, course, b"x" * 10)
    uid = up["upload_url"].split("/uploads/")[1].split("?")[0]
    headers = {"Content-Range": "bytes 0-9/10"}
    assert (
        client.put(
            f"/uploads/{uid}?exp=9999999999&sig=0", content=b"x" * 10, headers=headers
        ).status_code
        == 403
    )
    exp, sig = signing.sign(uid, -1)
    assert (
        client.put(
            f"/uploads/{uid}?exp={exp}&sig={sig}", content=b"x" * 10, headers=headers
        ).status_code
        == 403
    )
    # body longer than the range it claims
    assert client.put(up["upload_url"], content=b"x" * 11, headers=headers).status_code == 400
    # a range that runs past the declared size
    long = {"Content-Range": "bytes 0-19/10"}
    assert client.put(up["upload_url"], content=b"x" * 20, headers=long).status_code == 400


@pytest.mark.parametrize(
    "head, ok",
    [
        (MP4_HEAD, True),
        (b"\x00\x00\x00\x08wide\x00\x00\x00\x00mdat", True),  # old QuickTime
        (b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01", True),  # mkv / webm
        (b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n", False),
        (b"PK\x03\x04\x14\x00\x06\x00", False),  # zip, docx
        (b"not a video at all", False),
        (b"", False),
    ],
)
def test_looks_like_video(head, ok):
    from lecturelens.pipeline.media import looks_like_video

    assert looks_like_video(head) is ok


def test_non_video_is_refused_on_the_first_chunk(setup, db, queued):
    client, course = setup
    data = b"%PDF-1.7\n" + b"x" * 5000
    up = _start(client, course, data, name="notes.mp4")  # the name lies; the bytes don't
    r = _put(client, up["upload_url"], data, 0, 999, len(data))
    assert r.status_code == 415
    assert "isn't a video" in r.json()["detail"]
    assert db.execute("SELECT count(*) FROM lectures").fetchone()[0] == 0
    assert queued == []


def test_upload_rules(setup, sign_in):
    from fastapi.testclient import TestClient

    from lecturelens.api.main import create_app

    client, course = setup
    body = {"title": "t", "filename": "notes.pdf", "size": 10}
    assert client.post(f"/courses/{course}/lectures", json=body).status_code == 415
    body = {"title": "t", "filename": "big.mp4", "size": 10 * 1024**4}
    r = client.post(f"/courses/{course}/lectures", json=body)
    assert r.status_code == 413 and r.json()["detail"].endswith("The limit is 4 GB.")
    body = {"title": "t", "filename": "a.mp4", "size": 10}
    assert (
        TestClient(create_app()).post(f"/courses/{course}/lectures", json=body).status_code == 401
    )
    bob = TestClient(create_app())
    sign_in(bob, "bob@example.com")
    assert bob.post(f"/courses/{course}/lectures", json=body).status_code == 404


@pytest.mark.parametrize(
    "url, vid",
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ?si=abc", "dQw4w9WgXcQ"),
        ("https://youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://m.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://evil.com/watch?v=dQw4w9WgXcQ", None),
        ("https://youtube.com.evil.com/watch?v=dQw4w9WgXcQ", None),
        ("file:///etc/passwd", None),
        ("https://www.youtube.com/watch?v=short", None),
    ],
)
def test_youtube_links(url, vid):
    assert youtube_id(url) == vid


def test_youtube_import(setup, db, queued, monkeypatch, lecture_fixture):
    client, course = setup
    bad = client.post(f"/courses/{course}/lectures/import", json={"url": "https://vimeo.com/1"})
    assert bad.status_code == 422
    r = client.post(
        f"/courses/{course}/lectures/import",
        json={"url": "https://youtu.be/dQw4w9WgXcQ?t=3"},
    )
    assert r.status_code == 201
    lec = r.json()
    assert lec["source_url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert lec["status"] == "queued" and queued == [uuid.UUID(lec["id"])]

    video, _ = lecture_fixture

    def fake_download(url, out_dir, max_bytes):
        dst = out_dir / "source.mp4"
        dst.write_bytes(video.read_bytes())
        return dst, "Lecture 13: Dijkstra"

    monkeypatch.setattr(stages, "download_youtube", fake_download)
    stages.run_stage(uuid.UUID(lec["id"]), "fetch")
    stages.run_stage(uuid.UUID(lec["id"]), "probe")
    row = db.execute("SELECT title, storage_key, duration_s FROM lectures").fetchone()
    assert row[0] == "Lecture 13: Dijkstra"
    assert row[1].endswith("/source.mp4") and row[2] > 20


def test_progress_stream(setup, db):
    client, course = setup
    up = _start(client, course, b"x" * 10)
    lid = up["lecture_id"]
    db.execute(
        "INSERT INTO jobs (lecture_id, stage, status, progress) VALUES (%s, 'probe', 'done', 1),"
        " (%s, 'audio', 'running', 0.5)",
        (lid, lid),
    )
    events = lecture_routes.progress_events(uuid.UUID(lid), poll_s=0.01)
    first = next(events)
    assert first.startswith("event: progress") and '"status": "uploading"' in first
    db.execute("UPDATE lectures SET status = 'ready' WHERE id = %s", (lid,))
    last = next(events)
    assert '"status": "ready"' in last and '"progress": 1.0' in last
    assert next(events, None) is None  # stream ends once the lecture is ready

    # over HTTP it's an event stream, and other people can't open it
    r = client.get(f"/lectures/{lid}/events")
    assert r.headers["content-type"].startswith("text/event-stream")
    # without no-transform, the web app's proxy gzips the stream and holds it to the end
    assert "no-transform" in r.headers["cache-control"]
    assert "event: progress" in r.text
    detail = client.get(f"/lectures/{lid}").json()
    assert [s["stage"] for s in detail["stages"]][:2] == ["fetch", "probe"]
    from fastapi.testclient import TestClient

    from lecturelens.api.main import create_app

    assert TestClient(create_app()).get(f"/lectures/{lid}/events").status_code == 404

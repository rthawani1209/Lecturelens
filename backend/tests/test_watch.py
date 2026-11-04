"""The Watch screen's data, signed media links, and notes."""

import uuid
from urllib.parse import parse_qs, urlparse

import pytest

from lecturelens import signing
from lecturelens.api.routes.media import media_url
from lecturelens.pipeline import stages

pytestmark = pytest.mark.db


@pytest.fixture
def ready(db, lecture, fake_whisper, models_env):
    lid, truth = lecture
    stages.run_pipeline(lid)
    db.execute("UPDATE courses SET public = true")
    return lid, truth


def test_watch_has_video_transcript_and_frames(ready, client):
    lid, truth = ready
    body = client.get(f"/lectures/{lid}/watch").json()
    assert body["status"] == "ready" and body["course"]["title"] == "Algorithms"
    assert [line["text"] for line in body["transcript"]][0] == truth["slides"][0]["spoken"]
    assert body["frames"] and all("sig=" in f["thumb_url"] for f in body["frames"])
    assert {f["tag"] for f in body["frames"]} <= {
        "slide",
        "code",
        "whiteboard",
        "diagram",
        "professor",
        "other",
    }

    # the video streams in ranges, like a browser's <video> asks for it
    video = client.get(body["video_url"], headers={"Range": "bytes=0-99"})
    assert video.status_code == 206
    assert video.headers["content-type"] == "video/mp4" and len(video.content) == 100


def test_media_links_expire_and_cant_be_forged(ready, client):
    lid, _ = ready
    url = client.get(f"/lectures/{lid}/watch").json()["frames"][0]["thumb_url"]
    key = urlparse(url).path.removeprefix("/media/")
    sig = parse_qs(urlparse(url).query)["sig"][0]

    assert client.get(url).status_code == 200
    assert client.get(media_url(key, ttl_s=-1)).status_code == 403  # expired
    assert client.get(url.replace(sig, "0" * len(sig))).status_code == 403  # forged
    # a valid signature for one file doesn't open another
    other = url.replace(key, key.rsplit("/", 1)[0] + "/other.jpg")
    assert client.get(other).status_code == 403
    # links to paths outside storage are refused even when signed
    exp, s = signing.sign("media:../secrets.jpg", 60)
    assert client.get(f"/media/../secrets.jpg?exp={exp}&sig={s}").status_code in (403, 404)


def test_private_lecture_watch_looks_missing(ready, db, client):
    lid, _ = ready
    db.execute("UPDATE courses SET public = false")
    assert client.get(f"/lectures/{lid}/watch").status_code == 404
    assert client.get(f"/lectures/{uuid.uuid4()}/watch").status_code == 404


def test_notes_are_private_to_their_writer(ready, client, sign_in):
    lid, _ = ready
    assert client.post(f"/lectures/{lid}/notes", json={"t_s": 3, "text": "x"}).status_code == 401
    sign_in(client, "ada@example.com")
    note = client.post(f"/lectures/{lid}/notes", json={"t_s": 12.5, "text": " relax edges "}).json()
    assert note["text"] == "relax edges" and note["t_s"] == 12.5
    assert client.post(f"/lectures/{lid}/notes", json={"t_s": 1, "text": ""}).status_code == 422
    assert [n["id"] for n in client.get(f"/lectures/{lid}/notes").json()] == [note["id"]]

    client.post("/auth/logout")
    sign_in(client, "bob@example.com")
    assert client.get(f"/lectures/{lid}/notes").json() == []
    assert client.delete(f"/notes/{note['id']}").status_code == 404

    client.post("/auth/logout")
    sign_in(client, "ada@example.com")
    assert client.delete(f"/notes/{note['id']}").status_code == 204
    assert client.get(f"/lectures/{lid}/notes").json() == []

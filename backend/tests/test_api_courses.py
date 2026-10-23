import uuid

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db


@pytest.fixture
def client(database_url):
    from lecturelens.api.main import create_app

    return TestClient(create_app())


def _course(db, *, public: bool) -> uuid.UUID:
    gid = db.execute("INSERT INTO groups (name) VALUES ('g') RETURNING id").fetchone()[0]
    cid = db.execute(
        "INSERT INTO courses (group_id, code, title, public) VALUES (%s, '6.006', 'Algorithms', %s)"
        " RETURNING id",
        (gid, public),
    ).fetchone()[0]
    db.execute(
        "INSERT INTO lectures (course_id, title, position) VALUES (%s, 'Lecture 1', 1)", (cid,)
    )
    return cid


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_public_courses_listed_with_counts(client, db):
    _course(db, public=True)
    _course(db, public=False)
    body = client.get("/courses/public").json()
    assert len(body) == 1
    assert body[0]["lecture_count"] == 1


def test_private_course_looks_missing(client, db):
    private = _course(db, public=False)
    assert client.get(f"/courses/{private}/lectures").status_code == 404
    assert client.get(f"/courses/{uuid.uuid4()}/lectures").status_code == 404

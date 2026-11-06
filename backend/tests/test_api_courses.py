import uuid

import pytest

pytestmark = pytest.mark.db


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
    body = client.get("/health").json()
    assert body["status"] == "ok"
    # no TF Serving in tests: the models say so instead of failing the check
    assert set(body["models"]) == {"tagger", "reranker"}


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


def test_lectures_grouped_by_week(client, db):
    cid = _course(db, public=True)  # "Lecture 1" has no week yet
    db.execute(
        "INSERT INTO lectures (course_id, title, week, position) VALUES"
        " (%(c)s, 'Hashing', 2, 4), (%(c)s, 'Sorting', 2, 3), (%(c)s, 'Arrays', 1, 2)",
        {"c": cid},
    )
    body = client.get(f"/courses/{cid}/weeks").json()
    assert [w["week"] for w in body] == [1, 2, None]
    assert [lec["title"] for lec in body[1]["lectures"]] == ["Sorting", "Hashing"]
    assert body[2]["lectures"][0]["title"] == "Lecture 1"


def test_weeks_of_a_private_course_look_missing(client, db):
    private = _course(db, public=False)
    assert client.get(f"/courses/{private}/weeks").status_code == 404


def test_rename_and_delete_your_course(client, db, sign_in, storage):
    from fastapi.testclient import TestClient

    from lecturelens.api.main import create_app

    sign_in(client, "ada@example.com")
    cid = client.post("/courses", json={"title": "Algorithms"}).json()["id"]
    lid = db.execute(
        "INSERT INTO lectures (course_id, title, status) VALUES (%s, 'L1', 'ready') RETURNING id",
        (cid,),
    ).fetchone()[0]
    storage.put_file(f"lectures/{lid}/source.mp4", __file__)

    r = client.patch(f"/courses/{cid}", json={"title": " Algorithms II ", "code": "6.046"})
    assert (r.json()["title"], r.json()["code"]) == ("Algorithms II", "6.046")
    assert client.patch(f"/courses/{cid}", json={"title": "  "}).status_code == 422

    # someone else can't touch it, and public demo courses can't be changed
    bob = TestClient(create_app())
    sign_in(bob, "bob@example.com")
    assert bob.patch(f"/courses/{cid}", json={"title": "mine"}).status_code == 404
    assert bob.delete(f"/courses/{cid}").status_code == 404
    db.execute("UPDATE courses SET public = true WHERE id = %s", (cid,))
    assert bob.delete(f"/courses/{cid}").status_code == 404
    db.execute("UPDATE courses SET public = false WHERE id = %s", (cid,))

    assert client.delete(f"/courses/{cid}").status_code == 204
    assert db.execute("SELECT count(*) FROM lectures").fetchone()[0] == 0
    assert not storage.exists(f"lectures/{lid}/source.mp4")
    assert client.delete(f"/courses/{cid}").status_code == 404

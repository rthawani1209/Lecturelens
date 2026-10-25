"""Two users and a public course: each route must only show people what they may see."""

import uuid

import pytest

from lecturelens.search import engine

pytestmark = pytest.mark.db


@pytest.fixture
def world(client, db, sign_in):
    from fastapi.testclient import TestClient

    from lecturelens.api.main import create_app

    ada = client
    sign_in(ada, "ada@example.com")
    bob = TestClient(create_app())
    sign_in(bob, "bob@example.com")
    anon = TestClient(create_app())

    r = ada.post("/courses", json={"title": "Ada's algorithms", "terms": ["Dijkstra", " "]})
    assert r.status_code == 201
    private = r.json()["id"]
    gid = db.execute("INSERT INTO groups (name) VALUES ('MIT') RETURNING id").fetchone()[0]
    public = db.execute(
        "INSERT INTO courses (group_id, title, public) VALUES (%s, '6.006', true) RETURNING id",
        (gid,),
    ).fetchone()[0]
    return ada, bob, anon, private, str(public)


def test_course_list_shows_mine_and_public(world, db):
    ada, bob, anon, private, public = world
    assert {c["id"]: c["mine"] for c in ada.get("/courses").json()} == {
        private: True,
        public: False,
    }
    assert [c["id"] for c in bob.get("/courses").json()] == [public]
    assert [c["id"] for c in anon.get("/courses").json()] == [public]
    terms = db.execute("SELECT term FROM course_terms").fetchall()
    assert terms == [("Dijkstra",)]


def test_private_lectures_are_404_for_others(world):
    ada, bob, anon, private, public = world
    assert ada.get(f"/courses/{private}/lectures").status_code == 200
    assert bob.get(f"/courses/{private}/lectures").status_code == 404
    assert anon.get(f"/courses/{private}/lectures").status_code == 404
    assert anon.get(f"/courses/{public}/lectures").status_code == 200


def test_creating_courses_needs_an_account_and_your_own_group(world, db):
    ada, bob, anon, private, public = world
    assert anon.post("/courses", json={"title": "x"}).status_code == 401
    ada_group = db.execute(
        "SELECT group_id FROM courses WHERE id = %s", (uuid.UUID(private),)
    ).fetchone()[0]
    r = bob.post("/courses", json={"title": "sneaky", "group_id": str(ada_group)})
    assert r.status_code == 404


def test_search_only_covers_readable_courses(world, monkeypatch):
    ada, bob, anon, private, public = world
    seen = {}

    def fake_search(q, courses, **kw):
        seen["courses"] = {str(c) for c in courses}
        return []

    monkeypatch.setattr("lecturelens.api.routes.search.search", fake_search)
    ada.get("/search", params={"q": "heap"})
    assert seen["courses"] == {private, public}
    bob.get("/search", params={"q": "heap"})
    assert seen["courses"] == {public}
    # asking for someone else's course by id is a 404, not an empty result
    assert bob.get("/search", params={"q": "heap", "course": private}).status_code == 404
    assert engine.search("heap", []) == []

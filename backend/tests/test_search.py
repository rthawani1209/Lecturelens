"""Search over the synthetic lecture. Its narration and slides are known, so we can
say exactly which moment each query should land on."""

import uuid

import pytest
from fastapi.testclient import TestClient

from lecturelens.pipeline import stages
from lecturelens.search.engine import Candidate, collapse, fuse, search

SLIDE = {"graph": 0, "relax": 1, "dijkstra": 2, "runtime": 3}


@pytest.fixture
def indexed(db, lecture, fake_whisper, models_env):
    lid, truth = lecture
    stages.run_pipeline(lid)
    db.execute("UPDATE courses SET public = true")
    cid = db.execute("SELECT course_id FROM lectures WHERE id = %s", (lid,)).fetchone()[0]
    return lid, cid, truth


def _slide_at(truth, t):
    for i, s in enumerate(truth["slides"]):
        if s["start_s"] - 0.5 <= t < s["end_s"]:
            return i
    return None


@pytest.mark.db
@pytest.mark.parametrize(
    "query, mode, slide",
    [
        ("smallest estimate", "keyword", "dijkstra"),  # exact words
        ("lower the distance when a shorter path shows up", "meaning", "relax"),  # paraphrase
        ("Fibonacci heap", "visual", "runtime"),  # only written on the slide, never said
        ("python code on a dark screen", "visual", "relax"),  # what it looks like
        ("why must edge weights be non negative", "hybrid", "dijkstra"),
    ],
)
def test_query_lands_on_the_right_slide(indexed, query, mode, slide):
    lid, cid, truth = indexed
    hits = search(query, [cid], mode=mode, limit=3)
    assert hits, f"no hits for {query!r}"
    assert _slide_at(truth, hits[0].jump_s if mode != "visual" else hits[0].frame_t) == SLIDE[slide]


@pytest.mark.db
def test_other_courses_are_not_searched(indexed):
    assert search("smallest estimate", [uuid.uuid4()]) == []


@pytest.mark.db
def test_search_api(indexed, db):
    from lecturelens.api.main import create_app

    client = TestClient(create_app())
    body = client.get("/search", params={"q": "binary heap running time"}).json()
    assert body["hits"]
    top = body["hits"][0]
    assert top["thumb_url"].startswith("/media/lectures/")
    assert client.get(top["thumb_url"]).headers["content-type"] == "image/jpeg"
    # a private course is invisible to anonymous search and its media 404s
    db.execute("UPDATE courses SET public = false")
    assert client.get("/search", params={"q": "binary heap"}).json()["hits"] == []
    assert client.get(top["thumb_url"]).status_code == 404


def test_fuse_prefers_moments_found_by_several_retrievers():
    a = Candidate(1, "L", 0, 30, ranks={"keyword": 1})
    b = Candidate(2, "L", 300, 330, ranks={"keyword": 2, "meaning": 1})
    c = Candidate(3, "L", 600, 630, ranks={"meaning": 2})
    assert [x.segment_id for x, _ in fuse({1: a, 2: b, 3: c}, k=60)] == [2, 1, 3]


def test_collapse_merges_overlapping_windows():
    a = Candidate(1, "L", 0, 30)
    b = Candidate(2, "L", 15, 45)
    c = Candidate(3, "L", 600, 630)
    out = collapse([(a, 0.9), (b, 0.8), (c, 0.7)], limit=10)
    assert [x.segment_id for x, _ in out] == [1, 3]

"""Search over the synthetic lecture. Its narration and slides are known, so we can
say exactly which moment each query should land on."""

import uuid

import pytest

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
def test_keyword_mode_wants_more_than_one_stray_word(indexed):
    _, cid, _ = indexed
    assert search("smallest estimate", [cid], mode="keyword")
    # "estimate" is said, "pizza" never is: one shared word isn't a match
    assert search("estimate pizza", [cid], mode="keyword") == []


@pytest.mark.db
@pytest.mark.parametrize("mode", ["meaning", "text", "hybrid", "keyword"])
def test_nonsense_finds_nothing(indexed, mode):
    # meaning search has a nearest sentence for anything; it shouldn't offer it
    _, cid, _ = indexed
    assert search("xqzvbnm wibble", [cid], mode=mode) == []


@pytest.mark.db
def test_search_api(indexed, db, client, sign_in):
    body = client.get("/search", params={"q": "binary heap running time"}).json()
    assert body["hits"]
    top = body["hits"][0]
    assert top["thumb_url"].startswith("/media/lectures/") and "sig=" in top["thumb_url"]
    assert top["lecture_duration_s"] > 0 and top["lecture_position"] == 0
    thumb = client.get(top["thumb_url"])
    assert thumb.headers["content-type"] == "image/jpeg"
    assert thumb.headers["cache-control"].startswith("private")
    # a private course is invisible to anonymous search, so no links are handed out
    db.execute("UPDATE courses SET public = false")
    assert client.get("/search", params={"q": "binary heap"}).json()["hits"] == []
    # ...but members of the course's group still see it
    me = sign_in(client, "member@example.com")
    lid, cid, _ = indexed
    db.execute(
        "INSERT INTO group_members (group_id, user_id)"
        " SELECT group_id, %s FROM courses WHERE id = %s",
        (uuid.UUID(me["id"]), cid),
    )
    assert client.get("/search", params={"q": "binary heap"}).json()["hits"]


@pytest.mark.db
def test_tag_filter_keeps_only_moments_with_that_kind_of_frame(indexed, db, client):
    lid, cid, truth = indexed
    relax = truth["slides"][SLIDE["relax"]]
    # pin the tags so the test doesn't depend on the tagger
    db.execute("UPDATE frames SET tag = 'slide' WHERE lecture_id = %s", (lid,))
    db.execute(
        "UPDATE frames SET tag = 'code' WHERE lecture_id = %s AND t_s >= %s AND t_s < %s",
        (lid, relax["start_s"], relax["end_s"]),
    )
    hits = search("shortest path distance", [cid], mode="hybrid", limit=10, tag="code")
    assert hits
    assert {_slide_at(truth, h.jump_s) for h in hits} == {SLIDE["relax"]}
    assert search("shortest path distance", [cid], tag="whiteboard") == []

    body = client.get(
        "/search", params={"q": "lower the distance when a shorter path shows up", "tag": "code"}
    ).json()
    assert body["hits"] and all(h["tag"] == "code" for h in body["hits"])
    assert client.get("/search", params={"q": "relax", "tag": "cat"}).status_code == 422


def test_fuse_prefers_moments_found_by_several_retrievers():
    a = Candidate(1, "L", 0, 30, ranks={"keyword": 1})
    b = Candidate(2, "L", 300, 330, ranks={"keyword": 2, "meaning": 1})
    c = Candidate(3, "L", 600, 630, ranks={"meaning": 2})
    # b is the only one two retrievers agree on, whatever the weights
    assert fuse({1: a, 2: b, 3: c}, k=60)[0][0].segment_id == 2


def test_collapse_merges_overlapping_windows():
    a = Candidate(1, "L", 0, 30)
    b = Candidate(2, "L", 15, 45)
    c = Candidate(3, "L", 600, 630)
    out = collapse([(a, 0.9), (b, 0.8), (c, 0.7)], limit=10)
    assert [x.segment_id for x, _ in out] == [1, 3]

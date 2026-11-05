"""Odd input gets a 422 with a reason, never a 500 or a blank record."""

import pytest

pytestmark = pytest.mark.db


@pytest.fixture
def signed_in(client, sign_in):
    sign_in(client, "ada@example.com")
    return client


@pytest.mark.parametrize("title", [r"a\u0000b", r"\ud800", "   "])
def test_course_titles_that_cant_be_stored(signed_in, title):
    # raw JSON, the way a browser could send it (\ud800 is half an emoji)
    r = signed_in.post(
        "/courses", content=f'{{"title": "{title}"}}', headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 422, r.text


@pytest.mark.parametrize("t_s", ["NaN", "Infinity", "1e300"])
def test_note_times_must_be_real_times(signed_in, db, t_s):
    cid = signed_in.post("/courses", json={"title": "Algorithms"}).json()["id"]
    lid = db.execute(
        "INSERT INTO lectures (course_id, title, status) VALUES (%s, 'L1', 'ready') RETURNING id",
        (cid,),
    ).fetchone()[0]
    body = f'{{"t_s": {t_s}, "text": "hi"}}'
    r = signed_in.post(
        f"/lectures/{lid}/notes", content=body, headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 422, r.text

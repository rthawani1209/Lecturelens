import pytest

from lecturelens import mail
from lecturelens.api.routes import auth as auth_routes

pytestmark = pytest.mark.db


def _link_token() -> str:
    return mail.outbox[-1].get_content().split("token=")[1].split()[0]


def test_email_link_signs_in_once(client, db):
    assert client.get("/auth/me").status_code == 401
    assert client.post("/auth/email", json={"email": " Ada@Example.com "}).status_code == 204
    assert mail.outbox[-1]["To"] == "ada@example.com"
    token = _link_token()

    r = client.post("/auth/email/verify", json={"token": token})
    assert r.status_code == 200
    assert "httponly" in r.headers["set-cookie"].lower()
    assert client.get("/auth/me").json()["email"] == "ada@example.com"

    # links are single use
    assert client.post("/auth/email/verify", json={"token": token}).status_code == 400
    # only the hash is stored
    stored = db.execute("SELECT token_hash FROM login_tokens").fetchone()[0]
    assert token.encode() not in bytes(stored)


def test_new_user_gets_a_personal_group(client, db, sign_in):
    sign_in(client, "grace@example.com")
    sign_in(client, "grace@example.com")  # second login, same account
    assert db.execute("SELECT count(*) FROM users").fetchone()[0] == 1
    row = db.execute(
        "SELECT g.personal, m.role FROM groups g JOIN group_members m ON m.group_id = g.id"
    ).fetchall()
    assert row == [(True, "owner")]


def test_expired_link_is_refused(client, db):
    client.post("/auth/email", json={"email": "a@example.com"})
    db.execute("UPDATE login_tokens SET expires_at = now() - interval '1 second'")
    assert client.post("/auth/email/verify", json={"token": _link_token()}).status_code == 400


def test_logout_kills_the_session(client, sign_in):
    sign_in(client, "a@example.com")
    cookie = client.cookies.get("ll_session")
    assert client.post("/auth/logout").status_code == 204
    client.cookies.set("ll_session", cookie)  # replaying the old cookie doesn't work
    assert client.get("/auth/me").status_code == 401


@pytest.fixture
def google(monkeypatch):
    from lecturelens.config import get_settings

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    get_settings.cache_clear()
    profile = {"sub": "g-123", "email": "Ada@example.com", "email_verified": True, "name": "Ada"}
    monkeypatch.setattr(auth_routes, "google_profile", lambda code: profile)
    yield profile
    get_settings.cache_clear()


def test_google_sign_in(client, db, google):
    start = client.get("/auth/google/start", follow_redirects=False)
    assert start.status_code == 307
    assert start.headers["location"].startswith(auth_routes.GOOGLE_AUTH)
    state = client.cookies.get("ll_oauth_state")

    r = client.get(
        "/auth/google/callback", params={"code": "c", "state": state}, follow_redirects=False
    )
    assert r.status_code == 307 and "error" not in r.headers["location"]
    me = client.get("/auth/me").json()
    assert (me["email"], me["name"]) == ("ada@example.com", "Ada")
    assert db.execute("SELECT google_sub FROM users").fetchone()[0] == "g-123"


def test_google_links_to_existing_email_account(client, db, google, sign_in):
    first = sign_in(client, "ada@example.com")
    client.post("/auth/logout")
    client.get("/auth/google/start", follow_redirects=False)
    state = client.cookies.get("ll_oauth_state")
    client.get("/auth/google/callback", params={"code": "c", "state": state})
    assert client.get("/auth/me").json()["id"] == first["id"]


def test_google_rejects_wrong_state_and_unverified_email(client, google):
    client.get("/auth/google/start", follow_redirects=False)
    r = client.get(
        "/auth/google/callback", params={"code": "c", "state": "forged"}, follow_redirects=False
    )
    assert "error=google" in r.headers["location"]

    google["email_verified"] = False
    client.get("/auth/google/start", follow_redirects=False)
    state = client.cookies.get("ll_oauth_state")
    r = client.get(
        "/auth/google/callback", params={"code": "c", "state": state}, follow_redirects=False
    )
    assert "error=google" in r.headers["location"]
    assert client.get("/auth/me").status_code == 401


def test_google_off_without_client_id(client):
    assert client.get("/auth/google/start", follow_redirects=False).status_code == 404

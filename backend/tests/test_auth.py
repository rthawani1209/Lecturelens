import pytest

from lecturelens import mail
from lecturelens.api.routes import auth as auth_routes
from lecturelens.config import get_settings

pytestmark = pytest.mark.db


def _link_token() -> str:
    return mail.outbox[-1].get_content().split("token=")[1].split()[0]


def test_email_link_signs_in_once(client, db):
    assert client.get("/auth/me").status_code == 401
    assert client.post("/auth/email", json={"email": " Ada@Example.com "}).status_code == 204
    assert mail.outbox[-1]["To"] == "ada@example.com"
    # the link opens the web app's verify page, never a GET on the API
    assert "http://localhost:3000/signin/verify?token=" in mail.outbox[-1].get_content()
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


def test_too_many_links_for_one_address(client, db):
    for _ in range(5):
        assert client.post("/auth/email", json={"email": "b@example.com"}).status_code == 204
    r = client.post("/auth/email", json={"email": "B@example.com"})
    assert r.status_code == 429
    assert "15 minutes" in r.json()["detail"]
    # other addresses aren't affected, and expired links stop counting
    assert client.post("/auth/email", json={"email": "c@example.com"}).status_code == 204
    db.execute("UPDATE login_tokens SET expires_at = now() - interval '1 second'")
    assert client.post("/auth/email", json={"email": "b@example.com"}).status_code == 204


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


def test_no_email_sign_in_on_a_server_that_cant_send_mail(client, monkeypatch):
    monkeypatch.setenv("EMAIL_TO_LOG", "false")
    get_settings.cache_clear()
    try:
        assert client.get("/auth/providers").json()["email"] is False
        assert client.post("/auth/email", json={"email": "a@example.com"}).status_code == 404
        monkeypatch.setenv("SMTP_URL", "smtp://mail.example.com:587")
        get_settings.cache_clear()
        assert client.get("/auth/providers").json()["email"] is True
    finally:
        get_settings.cache_clear()


def test_providers_only_offer_google_when_configured(client):
    assert client.get("/auth/providers").json() == {
        "email": True,
        "google": False,
        "demo": False,
        "max_upload_bytes": 4 * 1024**3,
    }
    assert client.get("/auth/google/start", follow_redirects=False).status_code == 404


def test_session_answers_200_signed_in_or_not(client, sign_in):
    assert client.get("/auth/session").json() == {"user": None}
    sign_in(client, "ada@example.com")
    assert client.get("/auth/session").json()["user"]["email"] == "ada@example.com"


def test_demo_login_is_off_unless_enabled(client, db, monkeypatch):
    from lecturelens.config import get_settings

    assert client.post("/auth/demo").status_code == 404
    monkeypatch.setenv("DEMO_LOGIN", "1")
    get_settings.cache_clear()
    try:
        assert client.get("/auth/providers").json()["demo"] is True
        first = client.post("/auth/demo").json()
        assert first["email"].endswith("@demo.invalid")
        assert client.get("/auth/me").json()["id"] == first["id"]
        # every visitor gets their own account, so nobody sees another's uploads
        assert client.post("/auth/demo").json()["id"] != first["id"]
    finally:
        get_settings.cache_clear()


def test_demo_accounts_are_limited_per_address_and_expire(client, db, storage, monkeypatch):
    from lecturelens.config import get_settings

    monkeypatch.setenv("DEMO_LOGIN", "1")
    monkeypatch.setenv("DEMO_LOGINS_PER_HOUR", "2")
    monkeypatch.setenv("TRUST_FORWARDED_FOR", "1")
    get_settings.cache_clear()
    try:
        visitor = {"X-Forwarded-For": "203.0.113.7, 172.18.0.5"}
        assert client.post("/auth/demo", headers=visitor).status_code == 200
        first = client.post("/auth/demo", headers=visitor).json()
        r = client.post("/auth/demo", headers=visitor)
        assert r.status_code == 429 and "an hour" in r.json()["detail"]
        # someone else isn't held up by that visitor
        other = client.post("/auth/demo", headers={"X-Forwarded-For": "198.51.100.2"})
        assert other.status_code == 200

        # a day later the account goes, along with its course and its video
        course = client.post("/courses", json={"title": "Mine"}).json()["id"]
        lid = db.execute(
            "INSERT INTO lectures (course_id, title, status)"
            " VALUES (%s, 'L', 'ready') RETURNING id",
            (course,),
        ).fetchone()[0]
        storage.put_file(f"lectures/{lid}/source.mp4", __file__)
        db.execute("UPDATE users SET created_at = now() - interval '2 days'")
        assert auth_routes.remove_old_demo_accounts() == 3
        assert (
            db.execute("SELECT count(*) FROM courses WHERE id = %s", (course,)).fetchone()[0] == 0
        )
        assert not storage.exists(f"lectures/{lid}/source.mp4")
        assert first["email"].endswith("@demo.invalid")
    finally:
        get_settings.cache_clear()

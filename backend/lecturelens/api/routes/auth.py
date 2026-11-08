import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr

from ...auth import (
    create_session,
    end_session,
    finish_email_login,
    get_or_create_user,
    new_token,
    start_email_login,
)
from ...config import get_settings
from ...db import connection
from ...storage import get_storage
from ..client_ip import client_ip
from ..deps import SESSION_COOKIE, current_user, require_user

router = APIRouter(prefix="/auth", tags=["auth"])

STATE_COOKIE = "ll_oauth_state"
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"


class EmailIn(BaseModel):
    email: EmailStr


class TokenIn(BaseModel):
    token: str


class MeOut(BaseModel):
    id: str
    email: str
    name: str


def _set_session(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=s.session_days * 86400,
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
    )


@router.post("/email", status_code=204)
def email_link(body: EmailIn) -> None:
    if not _email_on():
        raise HTTPException(404, "Email sign-in isn't set up on this server")
    # same answer whether or not the address has an account
    if not start_email_login(body.email):
        raise HTTPException(
            429, "Too many sign-in links for this address. Try again in 15 minutes."
        )


# The emailed link opens the web app, which POSTs the token here. A plain GET
# would get spent by mail scanners that prefetch links.
@router.post("/email/verify", response_model=MeOut)
def email_verify(body: TokenIn, response: Response) -> dict:
    uid = finish_email_login(body.token)
    if uid is None:
        raise HTTPException(400, "this sign-in link is invalid or has expired")
    _set_session(response, create_session(uid))
    return _me(uid)


@router.get("/session")
def session(user: dict | None = Depends(current_user)) -> dict:
    """Who's signed in, as a 200 either way (the web app asks on every page)."""
    return {"user": _me(user["id"]) if user else None}


def _email_on() -> bool:
    s = get_settings()
    return bool(s.smtp_url) or s.email_to_log


@router.get("/providers")
def providers() -> dict:
    """Which sign-in buttons the web app should show."""
    s = get_settings()
    return {
        "email": _email_on(),
        "google": bool(s.google_client_id),
        "demo": s.demo_login,
        "max_upload_bytes": s.max_upload_bytes,  # so the upload page states the real limit
    }


@router.get("/google/start")
def google_start() -> RedirectResponse:
    s = get_settings()
    if not s.google_client_id:
        raise HTTPException(404, "Google sign-in isn't set up on this server")
    state = new_token()
    params = {
        "client_id": s.google_client_id,
        "redirect_uri": f"{s.api_url}/auth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    resp = RedirectResponse(f"{GOOGLE_AUTH}?{urlencode(params)}")
    resp.set_cookie(
        STATE_COOKIE, state, max_age=600, httponly=True, secure=s.cookie_secure, samesite="lax"
    )
    return resp


def google_profile(code: str) -> dict:
    """Trade the one-time code for the user's Google profile."""
    s = get_settings()
    with httpx.Client(timeout=10) as http:
        tok = http.post(
            GOOGLE_TOKEN,
            data={
                "code": code,
                "client_id": s.google_client_id,
                "client_secret": s.google_client_secret,
                "redirect_uri": f"{s.api_url}/auth/google/callback",
                "grant_type": "authorization_code",
            },
        )
        tok.raise_for_status()
        info = http.get(
            GOOGLE_USERINFO, headers={"Authorization": f"Bearer {tok.json()['access_token']}"}
        )
        info.raise_for_status()
        return info.json()


@router.get("/google/callback")
def google_callback(request: Request, code: str = "", state: str = "") -> RedirectResponse:
    s = get_settings()
    fail = RedirectResponse(f"{s.app_url}/signin?error=google")
    fail.delete_cookie(STATE_COOKIE)
    expected = request.cookies.get(STATE_COOKIE, "")
    # state must match the cookie we set, or someone else started this login
    if not code or not expected or not secrets.compare_digest(state, expected):
        return fail
    try:
        profile = google_profile(code)
    except httpx.HTTPError:
        return fail
    if not profile.get("email_verified") or not profile.get("email"):
        return fail
    with connection() as conn:
        uid = get_or_create_user(
            conn, profile["email"], profile.get("name", ""), google_sub=profile["sub"]
        )
    resp = RedirectResponse(s.app_url)
    resp.delete_cookie(STATE_COOKIE)
    _set_session(resp, create_session(uid))
    return resp


@router.post("/demo", response_model=MeOut)
def demo(request: Request, response: Response) -> dict:
    """Public demo only: sign in as a new throwaway account, no email needed."""
    s = get_settings()
    if not s.demo_login:
        raise HTTPException(404, "not found")
    ip = client_ip(request)
    with connection() as conn, conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('demo_signins'))")
        n = conn.execute(
            "SELECT count(*) AS n FROM demo_signins"
            " WHERE ip = %s AND at > now() - interval '1 hour'",
            (ip,),
        ).fetchone()["n"]
        if n >= s.demo_logins_per_hour:
            raise HTTPException(429, "That's a lot of demo accounts. Try again in an hour.")
        conn.execute("INSERT INTO demo_signins (ip) VALUES (%s)", (ip,))
        uid = get_or_create_user(conn, f"demo-{secrets.token_hex(6)}@demo.invalid", "Demo user")
    remove_old_demo_accounts()
    _set_session(response, create_session(uid))
    return _me(uid)


def remove_old_demo_accounts(max_age: str = "1 day") -> int:
    """Demo accounts last a day; then they go, with their courses and videos."""
    with connection() as conn, conn.transaction():
        users = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM users WHERE email LIKE '%%@demo.invalid'"
                " AND created_at < now() - %s::interval",
                (max_age,),
            )
        ]
        if not users:
            return 0
        groups = [
            r["group_id"]
            for r in conn.execute(
                "SELECT m.group_id FROM group_members m JOIN groups g ON g.id = m.group_id"
                " WHERE m.user_id = ANY(%s) AND g.personal",
                (users,),
            )
        ]
        lectures = [
            r["id"]
            for r in conn.execute(
                "SELECT l.id FROM lectures l JOIN courses c ON c.id = l.course_id"
                " WHERE c.group_id = ANY(%s)",
                (groups,),
            )
        ]
        conn.execute("DELETE FROM groups WHERE id = ANY(%s)", (groups,))
        conn.execute("DELETE FROM users WHERE id = ANY(%s)", (users,))
    storage = get_storage()
    for lid in lectures:
        storage.delete_prefix(f"lectures/{lid}/")
    return len(users)


@router.get("/me", response_model=MeOut)
def me(user: dict = Depends(require_user)) -> dict:
    return _me(user["id"])


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        end_session(token)
    response.delete_cookie(SESSION_COOKIE)


def _me(uid) -> dict:
    with connection() as conn:
        u = conn.execute("SELECT id, email, name FROM users WHERE id = %s", (uid,)).fetchone()
    return {"id": str(u["id"]), "email": u["email"], "name": u["name"]}

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
from ..deps import SESSION_COOKIE, require_user

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
    # same answer whether or not the address has an account
    start_email_login(body.email)


# The emailed link opens the web app, which POSTs the token here. A plain GET
# would get spent by mail scanners that prefetch links.
@router.post("/email/verify", response_model=MeOut)
def email_verify(body: TokenIn, response: Response) -> dict:
    uid = finish_email_login(body.token)
    if uid is None:
        raise HTTPException(400, "this sign-in link is invalid or has expired")
    _set_session(response, create_session(uid))
    return _me(uid)


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

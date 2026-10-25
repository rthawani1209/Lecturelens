from fastapi import Depends, HTTPException, Request

from ..auth import session_user

SESSION_COOKIE = "ll_session"


def current_user(request: Request) -> dict | None:
    """The signed-in user, or None for anonymous visitors (who can still use public courses)."""
    token = request.cookies.get(SESSION_COOKIE)
    return session_user(token) if token else None


def require_user(user: dict | None = Depends(current_user)) -> dict:
    if user is None:
        raise HTTPException(401, "sign in first")
    return user

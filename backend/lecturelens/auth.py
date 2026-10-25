"""Accounts and sessions.

People sign in with a one-time email link or with Google; either way they end up
with a random session token in an HttpOnly cookie. We only store sha256 hashes
of tokens, so reading the database doesn't let anyone sign in as someone else.
"""

import hashlib
import secrets
from datetime import timedelta
from uuid import UUID

import psycopg

from .config import get_settings
from .db import connection
from .mail import send

LOGIN_LINK_TTL = timedelta(minutes=15)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def normalize_email(email: str) -> str:
    return email.strip().lower()


def start_email_login(email: str) -> None:
    email = normalize_email(email)
    token = new_token()
    with connection() as conn:
        conn.execute(
            "INSERT INTO login_tokens (token_hash, email, expires_at) VALUES (%s, %s, now() + %s)",
            (token_hash(token), email, LOGIN_LINK_TTL),
        )
    link = f"{get_settings().api_url}/auth/email/verify?token={token}"
    send(
        email,
        "Your LectureLens sign-in link",
        f"Click to sign in to LectureLens:\n\n{link}\n\n"
        "The link works once and expires in 15 minutes. "
        "If you didn't ask for it, you can ignore this email.",
    )


def finish_email_login(token: str) -> UUID | None:
    """Spend a login link. Returns the user, or None if it's unknown, used or expired."""
    with connection() as conn:
        row = conn.execute(
            "UPDATE login_tokens SET used_at = now()"
            " WHERE token_hash = %s AND used_at IS NULL AND expires_at > now()"
            " RETURNING email",
            (token_hash(token),),
        ).fetchone()
        if row is None:
            return None
        return get_or_create_user(conn, row["email"])


def get_or_create_user(
    conn: psycopg.Connection, email: str, name: str = "", google_sub: str | None = None
) -> UUID:
    email = normalize_email(email)
    with conn.transaction():
        row = None
        if google_sub:
            row = conn.execute(
                "SELECT id FROM users WHERE google_sub = %s", (google_sub,)
            ).fetchone()
        if row is None:
            row = conn.execute("SELECT id FROM users WHERE email = %s", (email,)).fetchone()
        if row is not None:
            if google_sub:
                conn.execute(
                    "UPDATE users SET google_sub = %s, name = CASE WHEN name = '' THEN %s"
                    " ELSE name END WHERE id = %s",
                    (google_sub, name, row["id"]),
                )
            return row["id"]
        uid = conn.execute(
            "INSERT INTO users (email, name, google_sub) VALUES (%s, %s, %s) RETURNING id",
            (email, name, google_sub),
        ).fetchone()["id"]
        # everyone gets a personal group, so ownership is always "member of the group"
        gid = conn.execute(
            "INSERT INTO groups (name, personal) VALUES ('Personal', true) RETURNING id"
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO group_members (group_id, user_id, role) VALUES (%s, %s, 'owner')",
            (gid, uid),
        )
        return uid


def create_session(user_id: UUID) -> str:
    token = new_token()
    with connection() as conn:
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (%s, %s, now() + %s)",
            (token_hash(token), user_id, timedelta(days=get_settings().session_days)),
        )
    return token


def session_user(token: str) -> dict | None:
    with connection() as conn:
        return conn.execute(
            "SELECT u.id, u.email, u.name FROM sessions s JOIN users u ON u.id = s.user_id"
            " WHERE s.token_hash = %s AND s.expires_at > now()",
            (token_hash(token),),
        ).fetchone()


def end_session(token: str) -> None:
    with connection() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = %s", (token_hash(token),))

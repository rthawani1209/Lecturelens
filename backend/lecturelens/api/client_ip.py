"""The address a request came from, for per-visitor limits."""

from fastapi import Request

from ..config import get_settings


def client_ip(request: Request) -> str:
    if get_settings().trust_forwarded_for:
        # Caddy replaces whatever the client sent with the real address; the web
        # app's proxy appends its own after it
        first = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"

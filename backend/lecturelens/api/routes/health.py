import httpx
from fastapi import APIRouter, Response

from ...config import get_settings
from ...db import connection

router = APIRouter(tags=["health"])


def _model_state(base: str, name: str) -> str:
    """What TF Serving says about one model: AVAILABLE when it's serving."""
    if not base:
        return "not configured"
    try:
        r = httpx.get(f"{base.rstrip('/')}/v1/models/{name}", timeout=2)
        states = [v["state"] for v in r.json().get("model_version_status", [])]
        return "AVAILABLE" if "AVAILABLE" in states else (states[0] if states else "missing")
    except (httpx.HTTPError, ValueError):
        return "unreachable"


@router.get("/health")
def health(response: Response) -> dict:
    try:
        with connection() as conn:
            conn.execute("SELECT 1")
    except Exception:
        response.status_code = 503
        return {"status": "db unavailable"}
    # the models fall back to NumPy copies when TF Serving is down, so they're
    # reported here (smoke.py checks them) but don't make the API unhealthy
    s = get_settings()
    return {
        "status": "ok",
        "models": {
            "tagger": _model_state(s.tagger_url, "tagger"),
            "reranker": _model_state(s.reranker_url, "reranker"),
        },
    }

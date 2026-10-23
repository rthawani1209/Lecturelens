from fastapi import APIRouter, Response

from ...db import connection

router = APIRouter(tags=["health"])


@router.get("/health")
def health(response: Response) -> dict:
    try:
        with connection() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok"}
    except Exception:
        response.status_code = 503
        return {"status": "db unavailable"}

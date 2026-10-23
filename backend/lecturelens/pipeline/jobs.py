"""Job bookkeeping. One row per (lecture, stage) in `jobs`.

A stage is only marked done after its own writes commit, and every stage replaces
its previous output instead of appending. So rerunning a stage after a crash, or
running it twice by accident, leaves the same rows behind.
"""

from collections.abc import Callable
from uuid import UUID

from ..db import connection


def start(lecture_id: UUID, stage: str) -> int:
    with connection() as conn:
        row = conn.execute(
            """
            INSERT INTO jobs (lecture_id, stage, status, attempts, progress, error, updated_at)
            VALUES (%s, %s, 'running', 1, 0, NULL, now())
            ON CONFLICT (lecture_id, stage) DO UPDATE
               SET status = 'running', attempts = jobs.attempts + 1, progress = 0,
                   error = NULL, updated_at = now()
            RETURNING attempts
            """,
            (lecture_id, stage),
        ).fetchone()
        conn.execute(
            "UPDATE lectures SET status = 'processing' WHERE id = %s AND status <> 'processing'",
            (lecture_id,),
        )
    return row["attempts"]


def finish(lecture_id: UUID, stage: str) -> None:
    _set(lecture_id, stage, "done", progress=1.0)


def fail(lecture_id: UUID, stage: str, error: str) -> None:
    _set(lecture_id, stage, "failed", error=error[:2000])


def _set(
    lecture_id: UUID,
    stage: str,
    status: str,
    progress: float | None = None,
    error: str | None = None,
) -> None:
    with connection() as conn:
        conn.execute(
            """
            UPDATE jobs SET status = %s, progress = COALESCE(%s, progress), error = %s,
                   updated_at = now()
             WHERE lecture_id = %s AND stage = %s
            """,
            (status, progress, error, lecture_id, stage),
        )


def done_stages(lecture_id: UUID) -> set[str]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT stage FROM jobs WHERE lecture_id = %s AND status = 'done'", (lecture_id,)
        ).fetchall()
    return {r["stage"] for r in rows}


def progress_reporter(lecture_id: UUID, stage: str, step: float = 0.02) -> Callable[[float], None]:
    """Returns a callback that writes progress, but only every `step` so we don't
    hammer Postgres from inside whisper's segment loop."""
    last = [0.0]

    def report(p: float) -> None:
        if p - last[0] >= step or p >= 1.0:
            last[0] = p
            with connection() as conn:
                conn.execute(
                    "UPDATE jobs SET progress = %s, updated_at = now()"
                    " WHERE lecture_id = %s AND stage = %s",
                    (p, lecture_id, stage),
                )

    return report

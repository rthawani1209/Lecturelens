"""Celery worker. Start with: celery -A lecturelens.worker worker -l info"""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from celery import Celery
from celery.signals import worker_ready

from .config import get_settings
from .pipeline.media import MediaError
from .pipeline.stages import run_pipeline

settings = get_settings()
app = Celery("lecturelens", broker=settings.redis_url, backend=settings.redis_url)
app.conf.update(
    # ack only after the task finishes, so a worker killed mid-lecture gets its
    # message redelivered instead of silently dropping the lecture
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # Redis serves lower numbers first: a visitor's upload goes ahead of the
    # demo backlog instead of waiting hours behind it
    broker_transport_options={"visibility_timeout": 4 * 3600, "priority_steps": [0, 9]},
)

UPLOAD, BACKLOG = 0, 9


def send(lecture_id, priority: int = UPLOAD) -> None:
    process_lecture.apply_async((str(lecture_id),), priority=priority)


@app.task(
    bind=True, autoretry_for=(Exception,), retry_backoff=10, retry_backoff_max=600, max_retries=3
)
def process_lecture(self, lecture_id: str) -> None:
    lid = UUID(lecture_id)
    try:
        with _only_one(lid) as mine:
            if mine:
                run_pipeline(lid)
    except MediaError:
        # a broken or non-video file won't fix itself: fail now instead of retrying
        _mark_failed(lid)
    except Exception:
        if not _exists(lid):
            # deleted while it was processing; clear out whatever stages wrote meanwhile
            from .storage import get_storage

            get_storage().delete_prefix(f"lectures/{lid}/")
            return
        if self.request.retries >= self.max_retries:
            _mark_failed(lid)
        raise


@contextmanager
def _only_one(lid: UUID) -> Iterator[bool]:
    """Yields whether this task got the lecture. A lecture can be queued twice (a
    retry clicked twice, or Redis handing back a message after a restart), and two
    runs at once would trip over each other's files."""
    from .db import connection

    with connection() as conn:
        conn.autocommit = True  # session lock, held while the pipeline runs
        key = str(lid)
        got = conn.execute("SELECT pg_try_advisory_lock(hashtext(%s)) AS ok", (key,)).fetchone()
        try:
            yield got["ok"]
        finally:
            if got["ok"]:
                conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (key,))
            conn.autocommit = False


@worker_ready.connect
def requeue_interrupted(**_) -> None:
    """A deploy or crash kills the worker mid-lecture. Redis would only hand that
    message back hours later, so on start put every unfinished lecture back in line.
    The old messages go first: they may be stale or queued at the wrong priority,
    and the database knows everything that still needs doing."""
    from .db import connection

    # fine with the one worker we run; a second worker would need a lock here, or
    # its purge could drop tasks the first one just put back
    app.control.purge()
    with connection() as conn:
        rows = conn.execute(
            "SELECT l.id, l.created_by IS NULL AND c.public AS demo"
            " FROM lectures l JOIN courses c ON c.id = l.course_id"
            " WHERE l.status IN ('queued', 'processing')"
        ).fetchall()
    for r in rows:
        # the seeded demo courses are public and have no uploader
        send(r["id"], BACKLOG if r["demo"] else UPLOAD)


def _exists(lid: UUID) -> bool:
    from .db import connection

    with connection() as conn:
        return conn.execute("SELECT 1 FROM lectures WHERE id = %s", (lid,)).fetchone() is not None


def _mark_failed(lid: UUID) -> None:
    from .db import connection

    with connection() as conn:
        conn.execute("UPDATE lectures SET status = 'failed' WHERE id = %s", (lid,))

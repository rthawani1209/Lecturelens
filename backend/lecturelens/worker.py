"""Celery worker. Start with: celery -A lecturelens.worker worker -l info"""

from uuid import UUID

from celery import Celery

from .config import get_settings
from .pipeline.stages import run_pipeline

settings = get_settings()
app = Celery("lecturelens", broker=settings.redis_url, backend=settings.redis_url)
app.conf.update(
    # ack only after the task finishes, so a worker killed mid-lecture gets its
    # message redelivered instead of silently dropping the lecture
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_transport_options={"visibility_timeout": 4 * 3600},
)


@app.task(
    bind=True, autoretry_for=(Exception,), retry_backoff=10, retry_backoff_max=600, max_retries=3
)
def process_lecture(self, lecture_id: str) -> None:
    lid = UUID(lecture_id)
    try:
        run_pipeline(lid)
    except Exception:
        if self.request.retries >= self.max_retries:
            from .db import connection

            with connection() as conn:
                conn.execute("UPDATE lectures SET status = 'failed' WHERE id = %s", (lid,))
        raise

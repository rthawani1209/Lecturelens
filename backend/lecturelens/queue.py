from uuid import UUID


def enqueue(lecture_id: UUID) -> None:
    """Hand a lecture to the Celery worker (imported lazily so the API starts without Redis)."""
    from .worker import process_lecture

    process_lecture.delay(str(lecture_id))

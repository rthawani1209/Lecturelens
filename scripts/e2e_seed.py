"""Seed a clean database for the browser tests: one public course with one lecture
that has been through the real pipeline (whisper, frames, OCR, embeddings, tags).

The lecture is the synthetic one from backend/tests/fixtures/lecture.py, converted
to WebM because Playwright's Chromium build can't decode H.264.

  cd backend && python ../scripts/e2e_seed.py out.json
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from lecturelens.db import connection  # noqa: E402
from lecturelens.pipeline.stages import run_pipeline  # noqa: E402
from lecturelens.storage import get_storage  # noqa: E402
from tests.fixtures.lecture import build  # noqa: E402


def main(out: Path) -> None:
    work = Path(tempfile.mkdtemp(prefix="e2e-"))
    truth = build(work)
    webm = work / "lecture.webm"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(work / "lecture.mp4"),
            "-c:v",
            "libvpx-vp9",
            "-b:v",
            "300k",
            "-deadline",
            "realtime",
            "-cpu-used",
            "8",
            "-c:a",
            "libopus",
            str(webm),
        ],
        check=True,
    )
    with connection() as conn:
        gid = conn.execute("INSERT INTO groups (name) VALUES ('MIT OCW') RETURNING id").fetchone()[
            "id"
        ]
        cid = conn.execute(
            "INSERT INTO courses (group_id, code, title, term, license, public)"
            " VALUES (%s, 'E2E', 'Graph Algorithms Demo', 'Fall 2026', 'CC BY-NC-SA', true)"
            " RETURNING id",
            (gid,),
        ).fetchone()["id"]
        conn.execute("INSERT INTO course_terms VALUES (%s, 'Dijkstra')", (cid,))
        lid = conn.execute(
            "INSERT INTO lectures (course_id, title, week, position, storage_key, status)"
            " VALUES (%s, 'Lecture 1: Shortest Paths', 1, 1, 'seed/lecture.webm', 'queued')"
            " RETURNING id",
            (cid,),
        ).fetchone()["id"]
    get_storage().put_file("seed/lecture.webm", webm)
    run_pipeline(lid)
    with connection() as conn:
        status = conn.execute("SELECT status FROM lectures WHERE id = %s", (lid,)).fetchone()
    if status["status"] != "ready":
        sys.exit(f"seed lecture ended as {status['status']}")
    out.write_text(
        json.dumps(
            {
                "course_id": str(cid),
                "lecture_id": str(lid),
                "mp4": str(work / "lecture.mp4"),
                "slides": truth["slides"],
            },
            indent=2,
        )
    )
    print(f"seeded course {cid}, lecture {lid}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))

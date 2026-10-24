"""Load an OCW course folder (from fetch_ocw.py / the ocw-6.006-s20 release) as a public
course and run every lecture through the pipeline.

  python scripts/seed_demo.py data/ocw/6.006            # process in this process
  python scripts/seed_demo.py data/ocw/6.006 --queue    # hand lectures to Celery workers

Safe to rerun: existing lectures are matched by title and finished stages are skipped.
"""

import argparse
import json
import logging
import time
from pathlib import Path

from lecturelens.db import connection
from lecturelens.db.migrate import migrate
from lecturelens.pipeline.stages import run_pipeline
from lecturelens.storage import get_storage

# Spelling hints for whisper (passed as hotwords).
TERMS_6006 = [
    "Dijkstra",
    "Bellman-Ford",
    "Johnson's algorithm",
    "Floyd-Warshall",
    "Karatsuba",
    "AVL",
    "heapsort",
    "merge sort",
    "radix sort",
    "counting sort",
    "BFS",
    "DFS",
    "topological sort",
    "amortized",
    "asymptotic",
    "Fibonacci",
    "SRTBOT",
    "memoization",
    "subproblem",
    "DAG",
    "NP-complete",
    "NP-hard",
    "pseudopolynomial",
    "subset sum",
    "knapsack",
    "hash table",
    "universal hashing",
    "binary search tree",
    "priority queue",
    "relaxation",
    "Demaine",
    "Jason Ku",
    "Solomon",
    "Theta",
    "big O",
    "log n",
]


def ensure_course(manifest: dict) -> str:
    with connection() as conn:
        row = conn.execute("SELECT id FROM courses WHERE code = '6.006' AND public").fetchone()
        if row:
            return row["id"]
        gid = conn.execute(
            "INSERT INTO groups (name) VALUES ('MIT OpenCourseWare') RETURNING id"
        ).fetchone()["id"]
        cid = conn.execute(
            """INSERT INTO courses (group_id, code, title, term, public, license)
               VALUES (%s, '6.006', 'Introduction to Algorithms', 'Spring 2020', true, %s)
               RETURNING id""",
            (gid, f"{manifest['license']} · {manifest['attribution']}"),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO course_terms (course_id, term) SELECT %s, unnest(%s::text[])",
            (cid, TERMS_6006),
        )
        return cid


def ensure_lecture(course_id: str, folder: Path, lec: dict) -> str:
    title = lec["title"] or f"Lecture {lec['number']}"  # OCW titles already say "Lecture N: ..."
    with connection() as conn:
        row = conn.execute(
            "SELECT id FROM lectures WHERE course_id = %s AND position = %s",
            (course_id, lec["number"]),
        ).fetchone()
        if row:
            return row["id"]
        key = f"ocw/6.006/{lec['video']}"
        get_storage().put_file(key, folder / lec["video"])
        return conn.execute(
            """INSERT INTO lectures
                   (course_id, title, week, position, status, storage_key, source_url)
               VALUES (%s, %s, %s, %s, 'queued', %s, %s) RETURNING id""",
            (course_id, title, (lec["number"] + 1) // 2, lec["number"], key, lec["page"]),
        ).fetchone()["id"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--queue", action="store_true", help="send to Celery instead of running here")
    ap.add_argument("--only", type=int, nargs="*", help="lecture numbers to process")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    migrate()
    manifest = json.loads((args.folder / "manifest.json").read_text())
    course_id = ensure_course(manifest)
    for lec in manifest["lectures"]:
        if args.only and lec["number"] not in args.only:
            continue
        lid = ensure_lecture(course_id, args.folder, lec)
        if args.queue:
            from lecturelens.worker import process_lecture

            process_lecture.delay(str(lid))
            continue
        t0 = time.time()
        run_pipeline(lid)
        logging.info("lecture %s done in %.0fs", lec["number"], time.time() - t0)


if __name__ == "__main__":
    main()

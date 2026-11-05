"""Load an OCW course folder (from fetch_ocw.py / the ocw-* releases) as a public
course and run every lecture through the pipeline.

  python scripts/seed_demo.py data/ocw/6.006            # process in this process
  python scripts/seed_demo.py data/ocw/6.006 --queue    # hand lectures to Celery workers
  python scripts/seed_demo.py data/ocw/18.06            # same for the other courses

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

TERMS_6100L = [
    "Python",
    "Ana Bell",
    "int",
    "float",
    "boolean",
    "string",
    "tuple",
    "dictionary",
    "for loop",
    "while loop",
    "bisection search",
    "guess and check",
    "approximation",
    "epsilon",
    "indexing",
    "slicing",
    "immutable",
    "iteration",
]

TERMS_1806 = [
    "Strang",
    "matrix",
    "matrices",
    "elimination",
    "pivot",
    "row picture",
    "column picture",
    "linear combination",
    "Gauss-Jordan",
    "inverse",
    "invertible",
    "singular",
    "upper triangular",
    "permutation",
    "LU",
    "transpose",
]

# folder name -> (code, title, term, spelling hints)
COURSES = {
    "6.006": ("6.006", "Introduction to Algorithms", "Spring 2020", TERMS_6006),
    "6.100L": (
        "6.100L",
        "Introduction to CS and Programming using Python",
        "Fall 2022",
        TERMS_6100L,
    ),
    "18.06": ("18.06", "Linear Algebra", "Spring 2010", TERMS_1806),
}


def ensure_course(folder: Path, manifest: dict) -> str:
    code, title, term, terms = COURSES[folder.name]
    with connection() as conn:
        row = conn.execute("SELECT id FROM courses WHERE code = %s AND public", (code,)).fetchone()
        if row:
            return row["id"]
        gid = (
            conn.execute("SELECT id FROM groups WHERE name = 'MIT OpenCourseWare'").fetchone()
            or conn.execute(
                "INSERT INTO groups (name) VALUES ('MIT OpenCourseWare') RETURNING id"
            ).fetchone()
        )
        cid = conn.execute(
            """INSERT INTO courses (group_id, code, title, term, public, license)
               VALUES (%s, %s, %s, %s, true, %s)
               RETURNING id""",
            (gid["id"], code, title, term, f"{manifest['license']} · {manifest['attribution']}"),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO course_terms (course_id, term) SELECT %s, unnest(%s::text[])",
            (cid, terms),
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
        key = f"ocw/{folder.name}/{lec['video']}"
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
    course_id = ensure_course(args.folder, manifest)
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

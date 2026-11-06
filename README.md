# LectureLens

[![CI](https://github.com/rthawani1209/lecturelens/actions/workflows/ci.yml/badge.svg)](https://github.com/rthawani1209/lecturelens/actions/workflows/ci.yml)

Search your recorded lectures and jump to the exact second something was explained, whether it was said out loud or only written on a slide or whiteboard. Then ask questions about the lectures and study from flashcards built from what the professor actually said.

## Results

All numbers come from committed results files and are listed with the command that
reproduces them in [docs/CLAIMS.md](docs/CLAIMS.md).

| What | Number | Where it comes from |
|---|---|---|
| Search quality, MIT 6.006 held-out test questions (38) | NDCG@10 **0.786**, right moment in the top 5 for **85.5%** | `ml/eval/results_test.json` (default: meaning search) |
| Same default on courses never used for tuning | NDCG@10 0.834 on 18.06, 0.775 on 6.100L | `ml/eval/results_18.06.json`, `results_6.100L.json` |
| Keras re-ranker on top of hybrid search | recall@5 81.6% → **88.2%** (NDCG flat) | `ml/eval/results_test.json` |
| Frame tagger (MobileNetV3, TF Serving) on hand-checked frames | **82.4%** vs 67.1% for CLIP zero-shot, 7.7x faster on CPU | `ml/tagger/results.json` |
| Search latency, meaning search on a 4-CPU Linux box | p50 21 ms | `ml/eval/results_test.json` |

The honest part: plain meaning search beat the fused and re-ranked versions on 6.006,
so it's the default, and a CI gate keeps it that way. The write-up is in
[docs/INTERVIEW.md](docs/INTERVIEW.md).

## What you can do

- **Search** a course by meaning or keyword. Each result jumps the video to the second
  it was said or shown, with filters for slides, code, whiteboard, diagrams or the
  professor.
- **Watch** with a synced transcript, a strip of every board and slide, J/K/L and speed
  keys, captions, and private notes pinned to timestamps.
- **Upload** a video (resumable, survives a dropped connection) or import from YouTube,
  then watch the pipeline run live. Failed lectures can be retried or deleted.
- **Study** with flashcards for each lecture (spaced repetition), and ask questions.
  Every sentence of an answer cites the second it came from, and it says "not covered"
  instead of guessing.

## How it works

1. **Process.** A Celery worker turns each lecture into timestamped sentences
   (faster-whisper, with course vocabulary for terms like "Dijkstra") and a snapshot of
   every new slide or board (ffmpeg scene detection, near-duplicate removal, OCR).
2. **Understand.** Sentences and snapshots become vectors (MiniLM for text, CLIP for
   images) stored in Postgres with pgvector.
3. **Two TensorFlow models.** A MobileNetV3 frame tagger distilled from CLIP, and a
   re-ranker trained with a pairwise ranking loss. TF Serving serves both.
4. **Search.** Keyword (Postgres full-text), meaning, slide text and image search,
   merged with reciprocal rank fusion. Meaning search is the default.
5. **Study.** Claude writes cards and cited answers when an API key is set. Without one,
   it falls back to fill-in-the-blank cards and quoted passages, with per-user AI limits.

More detail in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Repo layout

```
backend/            Python API (FastAPI) and pipeline workers
  lecturelens/
    api/            HTTP routes: auth, courses, lectures, uploads, search, watch, study, media
    db/             connection pool + migration runner
    pipeline/       processing stages: fetch, probe, audio, transcribe, frames, OCR, embed, tag
    search/         hybrid search engine, NumPy fusion (RRF), metrics, re-ranker
    study/          flashcards (Claude or cloze), spaced repetition, cited answers
    access.py       who can read or change each course and lecture
    ai.py           Claude client and per-user limits
    auth.py         email-link and Google sign-in, sessions
    worker.py       Celery worker that runs the pipeline
  migrations/       SQL schema, applied in order
  tests/            pytest; fixtures/ builds a synthetic lecture with a synthetic voice
frontend/           Next.js web app
  src/              screens and components
  e2e/              Playwright tests against the real stack
ml/                 training and evaluation (separate venv: ml/requirements.txt)
  eval/             hand-labeled questions for three MIT courses + the evaluation script
  rerank/           re-ranker dataset, training and the CI gate
  tagger/           CLIP-teacher labels + MobileNetV3 frame tagger
  serving/          TF Serving config
scripts/            check.sh (same lint + tests as CI), e2e.sh, OCW downloader, demo seeding
deploy/             one-server production setup: bootstrap script, compose file, Caddy, smoke test
docs/               ARCHITECTURE, CLAIMS, INTERVIEW
models/             pretrained models (downloaded, not committed)
docker-compose.yml  local stack: Postgres + pgvector, Redis, MinIO, TF Serving, API, worker, web
```

## Run it locally

Needs Docker. No cloud accounts.

```bash
./scripts/get_models.sh        # ~800 MB: whisper, MiniLM, CLIP + the frame tagger (from this repo's releases)
docker compose up --build
open http://localhost:3000
```

Load a demo course. The lectures are mirrored in this repo's releases (`ocw-6.006-s20`,
`ocw-6.100l`, `ocw-18.06`); download one into `data/ocw/<course>/`, then:

```bash
python scripts/seed_demo.py data/ocw/6.006 --queue
```

Everything CI runs (lint, backend and model tests, frontend checks, browser tests):

```bash
TEST_DATABASE_URL=postgresql://lecturelens:lecturelens@localhost:5432/lecturelens_test scripts/check.sh
```

## Deploy it

One server with 4 vCPUs and 8 GB of memory runs everything (Hetzner CX32 or similar,
Ubuntu 24.04). As root on the new server:

```bash
curl -fsSL https://raw.githubusercontent.com/rthawani1209/lecturelens/main/deploy/bootstrap.sh | bash
```

Or paste `deploy/cloud-init.yaml` as the server's user data when creating it, and it
runs by itself. The script installs Docker, writes `deploy/.env` with fresh secrets,
downloads the models and the MIT lectures, starts the stack behind Caddy with an
HTTPS certificate for `<server-ip>.sslip.io`, and queues the lectures (a few hours on
CPU; the site works while they process). A timer checks `main` every 15 minutes and
rebuilds once a new commit's GitHub checks have all passed. The public site has a "Try it without an account"
button and caps uploads per day; both are settings in `deploy/.env`.

Every night at 03:30 the server dumps the database and copies the uploaded files to
`/var/backups/lecturelens` (7 dumps and 2 file copies are kept). How to restore is at
the top of `deploy/backup.sh`.

Check a running site end to end:

```bash
python3 deploy/smoke.py https://<server-ip>.sslip.io clip.mp4 "a phrase said in the clip"
```

## Data

The demo course is [MIT 6.006 Introduction to Algorithms (Spring 2020)](https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-spring-2020/) from MIT OpenCourseWare. The extra evaluation uses lectures 1-3 of [6.100L (Fall 2022)](https://ocw.mit.edu/courses/6-100l-introduction-to-cs-and-programming-using-python-fall-2022/) and [18.06 (Spring 2010)](https://ocw.mit.edu/courses/18-06-linear-algebra-spring-2010/). All are used under CC BY-NC-SA 4.0.

# LectureLens

[![CI](https://github.com/rthawani1209/lecturelens/actions/workflows/ci.yml/badge.svg)](https://github.com/rthawani1209/lecturelens/actions/workflows/ci.yml)

Search your recorded lectures and jump to the exact second something was explained, whether it was said out loud or only written on a slide or whiteboard. Then ask questions about the lectures and study from flashcards built from what the professor actually said.

> Work in progress. The demo video, live link and results table land here once the pipeline and models are trained.

## How it works

1. **Process.** A Python pipeline turns each lecture into timestamped sentences (faster-whisper) and a snapshot of every new slide or board (ffmpeg scene detection + OCR).
2. **Understand.** Sentences and snapshots become vectors that capture meaning (a sentence embedder for text, CLIP for images), stored in Postgres with pgvector.
3. **Two models trained in TensorFlow.** A MobileNetV3 frame tagger (slide / code / whiteboard / professor) distilled from CLIP, and a re-ranker trained with a pairwise ranking loss.
4. **Search.** Keyword search and meaning search run together, get merged with reciprocal rank fusion, then re-ranked. Every result links to the second it came from.
5. **Study.** Grounded answers with timestamp citations, flashcards with spaced repetition, and quizzes.

## Repo layout

```
backend/            Python API (FastAPI) and pipeline workers
  lecturelens/
    api/            HTTP routes
    db/             connection pool + migration runner
    pipeline/       processing stages: probe, audio, transcribe, keyframes, OCR
    search/         NumPy fusion (RRF), brute-force index, ranking metrics
    worker.py       Celery worker that runs the pipeline
  migrations/       SQL schema, applied in order
  tests/            unit + Postgres tests; fixtures/ builds a synthetic lecture
ml/                 TensorFlow training for the frame tagger and re-ranker (coming)
frontend/           Next.js web app (coming)
infra/              Google Cloud deploy (coming)
scripts/            model export, MIT OCW downloader, get_models.sh
docs/               ARCHITECTURE, DECISIONS, INTERVIEW, EXERCISE (coming)
models/             pretrained models (downloaded, not committed)
docker-compose.yml  local stack: Postgres + pgvector, Redis, MinIO, API, worker
```

## Run it locally

Needs Docker. No cloud accounts.

```bash
./scripts/get_models.sh        # ~800 MB: whisper, MiniLM, CLIP (from this repo's releases)
docker compose up --build
curl localhost:8000/health
```

Backend tests (needs Postgres with pgvector; DB tests are skipped without it):

```bash
cd backend
pip install -e '.[dev]'
pytest
```

## Data

The demo course is [MIT 6.006 Introduction to Algorithms (Spring 2020)](https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-spring-2020/) from MIT OpenCourseWare, used under CC BY-NC-SA 4.0.

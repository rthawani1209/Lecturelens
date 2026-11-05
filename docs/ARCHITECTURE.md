# How LectureLens fits together

```
browser ──> Next.js (web, :3000) ──/api──> FastAPI (api, :8000) ──> Postgres + pgvector
                                              │    │                  ▲
                                              │    └── Redis queue ──> Celery worker
                                              │                        │   ffmpeg, whisper, tesseract,
                                              │                        │   MiniLM, CLIP (ONNX)
                                              ├── object storage <─────┘   (MinIO locally)
                                              ├── TF Serving (frame tagger + re-ranker)
                                              └── Claude (cards and answers, optional)
```

## The web app

Next.js serves every screen. The browser only ever talks to the web app's own origin:
`/api/*` is proxied to FastAPI, so the session cookie is first-party and HttpOnly, and
the content security policy can say "only this origin" for everything. The server only
pre-renders public data (the list of public courses); anything tied to an account is
fetched in the browser with the user's cookie.

## Accounts and access

Sign-in is passwordless: a one-time email link (5 unused links per address at most) or
Google. Only sha256 hashes of link and session tokens are stored. Every course belongs
to a group, and every route checks membership through `access.py`. A course you can't
see answers 404, the same as one that doesn't exist, so ids can't be probed.

## Getting a lecture in

Uploads use the same resumable protocol as Google Cloud Storage: the client sends
chunks with `Content-Range`, and after a dropped connection it asks how much arrived
and carries on from there. The first chunk is checked by its bytes (an MP4 or Matroska
header), not its name, and the size limit is checked before anything is stored. When
the last chunk lands, the file is hashed; if the same course already has that video,
the upload points at the existing lecture instead of making a copy. YouTube links are
downloaded by the worker with yt-dlp, using a URL we build from the video id rather
than the one the user typed.

## The pipeline

A Celery worker runs the stages in order: fetch, probe, audio, transcribe, frames, OCR,
embed text, embed frames, tag. Each stage records its state in a `jobs` row and is
idempotent, so a crash or a retry picks up at the first unfinished stage instead of
starting over. Progress goes to the database, and the API streams it to the Upload
screen with server-sent events.

- **Transcribe:** faster-whisper, with the course's vocabulary passed as hotwords.
- **Frames:** ffmpeg scene detection, then near-duplicate removal, then Tesseract OCR.
  One frame that times out in OCR is skipped, not fatal.
- **Embed:** MiniLM sentence vectors and CLIP image vectors, both ONNX on CPU, stored
  in pgvector.
- **Tag:** the MobileNetV3 frame tagger through TF Serving. If TF Serving is down, a
  CLIP probe tags frames instead, so the lecture still finishes.

## Search

`search/engine.py` runs up to four retrievers: Postgres full-text (keyword), pgvector
over sentence vectors (meaning), full-text over slide OCR (text on screen), and CLIP
(images). Their lists are merged with reciprocal rank fusion, optionally re-scored by
the re-ranker, and collapsed into moments with a jump time. Meaning-only is the
default because it scored best on validation; `ml/rerank/gate.py` fails CI if the
default ever falls below a single retriever. The API loads the ONNX models in the
background at startup, so the first search isn't the slow one.

## Watching

Video, thumbnails and frames are served through HMAC-signed URLs that expire after 15
minutes; the player asks for a fresh link if one expires mid-lecture. Captions come
from the same transcript that search uses. Notes are private to the person who wrote
them.

## Study and Ask

When a lecture is opened in Study for the first time, the API writes its deck. With an
API key, Claude writes question and answer cards from the transcript (structured
output, each card pinned to a second of the lecture). Without one, the cards are
fill-in-the-blank: whole sentences from the lecture that contain a term the course
says rarely and the slides also show. Reviews use SM-2 spaced repetition.

Ask retrieves the closest passages (keyword plus meaning), numbers them, and sends
them to Claude as quoted data with a schema that makes every sentence cite a passage.
Uncited sentences are dropped, and if nothing survives, the answer is "not covered".
Without a key it quotes the best passages instead. Every AI call is logged with its
token count, and per-user limits apply per minute, day and month.

## Testing

- `backend/tests`: pytest against a real Postgres, using a synthetic lecture
  generated during the test run (rendered slides plus synthesized speech).
- `ml/tests`: loads both SavedModels the way TF Serving does.
- `frontend/src/**/*.test.ts`: Vitest for the upload client and formatting.
- `frontend/e2e`: Playwright against the whole stack started by `scripts/e2e.sh`,
  including a phone-width pass, and any console error fails the test.

`scripts/check.sh` runs all of it, the same as CI.

## Running it in public

`deploy/` runs the whole stack on one server. Caddy is the only thing listening on
the internet; it gets an HTTPS certificate and forwards to the web app, which forwards
`/api` to FastAPI as above. Storage is a Docker volume shared by the API and the
worker instead of MinIO, since there is only one machine. The worker processes one
lecture at a time so whisper and OCR can't run the server out of memory. Visitors can
press "Try it without an account" to get a throwaway account of their own, and
uploads are capped per account and per day so a public demo can't be run up. A
systemd timer pulls `main` every 15 minutes and rebuilds, and the Deploy check
workflow starts this same stack on a fresh machine and runs `deploy/smoke.py` against
it whenever the backend or the deploy files change.

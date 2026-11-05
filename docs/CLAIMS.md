# Claims and proof

Every statement about LectureLens that goes on a resume, where to see it's true, and
how to reproduce it. Numbers come from committed results files, never typed in by hand.
Status: **done** = built and proven; **planned** = not built yet (don't claim it yet);
**cut** = dropped from scope (don't claim it).

Repro commands assume the setup in the README (`scripts/get_models.sh`, Postgres with
pgvector, the demo course processed with `scripts/seed_demo.py`).

## Search

| Claim | Proof | Reproduce | Number | Status |
|---|---|---|---|---|
| Hybrid search: keyword (Postgres full-text) + meaning (pgvector) + slide text + CLIP, merged with reciprocal rank fusion | `backend/lecturelens/search/engine.py`; `backend/tests/test_search.py` (each query type lands on the right slide of a synthetic lecture) | `cd backend && pytest tests/test_search.py` | | done |
| Evaluated on hand-labeled questions over MIT 6.006, with held-out test lectures; every choice made on val, test reported once | `ml/eval/queries.jsonl` (100 queries: 62 val, 38 test), `ml/eval/results_test.json`, `ml/eval/results_val.json` | `python ml/eval/evaluate.py --split test` | test NDCG@10: meaning 0.786, tuned hybrid 0.719, keyword 0.523 | done |
| Choices made on 6.006 checked on two other MIT courses never used for tuning: 6.100L (Python, slides) and 18.06 (linear algebra, chalkboard), 3 lectures each | `ml/eval/queries_6.100L.jsonl` (16 queries), `ml/eval/queries_18.06.jsonl` (15), `ml/eval/results_6.100L.json`, `ml/eval/results_18.06.json` | `python scripts/seed_demo.py data/ocw/18.06`; `python ml/eval/evaluate.py --course 18.06` | NDCG@10 of the default (meaning): 18.06 0.834 (best of all methods), 6.100L 0.775 (best there: day 3 hybrid weights, which count slide text, 0.848). Small sets, so read these as a sanity check | done |
| Semantic search is the default because it was best on val; a CI gate fails if the default drops below any single retriever | `backend/lecturelens/config.py` (`search_mode`), `ml/rerank/gate.py`, `test_gate_default_matches_the_api_default` | `cd backend && pytest tests/test_rerank.py` | val NDCG@10 meaning 0.756 vs best combined 0.759 (tie, under the preset +0.01 bar) | done |
| Ranking metrics and fusion written in NumPy, tested against hand-worked examples | `backend/lecturelens/search/{fusion,metrics}.py`, `backend/tests/test_{fusion,metrics}.py` | `cd backend && pytest tests/test_fusion.py tests/test_metrics.py` | | done |
| Fusion weights tuned on val (grid search) instead of hand-picked | `ml/eval/tune_rrf.py`, `ml/eval/rrf_tuning_val.json`, `hybrid_day3_weights` vs `hybrid` in `ml/eval/results_test.json` | `python ml/eval/tune_rrf.py`; `python ml/eval/evaluate.py --split test` | hybrid NDCG@10 0.655 → 0.719 | done |
| Keras RankNet re-ranker (pairwise loss) over 25 NumPy features on top of tuned hybrid, beating a logistic regression baseline | `ml/rerank/{build_dataset,train}.py`, `ml/rerank/README.md`, `backend/lecturelens/search/rerank.py` | `ml/.venv/bin/python ml/rerank/train.py`; `python ml/eval/evaluate.py --split test` | recall@5 81.6% → 88.2%, NDCG@10 flat (0.719 → 0.720; LR 0.696); semantic-only is higher at 0.786, so it is the default | done |
| Backend runs the re-ranker in NumPy and matches Keras on fixed inputs | `test_numpy_forward_matches_keras_on_fixed_inputs` in `backend/tests/test_rerank.py`, `backend/tests/data/rerank_fixed.json` | `cd backend && pytest tests/test_rerank.py` | | done |
| Visual filters (slides, code, whiteboard, diagram, professor) from the frame tagger | `tag=` on `GET /search`, `_with_tag` in `backend/lecturelens/search/engine.py`, `test_tag_filter_keeps_only_moments_with_that_kind_of_frame` | `cd backend && pytest tests/test_search.py -k tag` | | done |

## Frame tagger (TensorFlow)

| Claim | Proof | Reproduce | Number | Status |
|---|---|---|---|---|
| MobileNetV3 fine-tuned in Keras on CLIP teacher labels (distillation) | `ml/tagger/train.py`, `ml/tagger/README.md` | `ml/.venv/bin/python ml/tagger/train.py` | | done |
| Accuracy on hand-checked frames from held-out lectures, as served by TF Serving | `ml/tagger/README.md`, `ml/tagger/results.json`, `ml/tagger/data/hand_labels.csv` (300 checked, 85 in the test lectures) | as above, then tag the demo course through `docker compose up serving` | **82.4%** served (83.5% in Keras; CLIP zero-shot 67.1%) | done |
| Faster and smaller than CLIP on CPU | `ml/tagger/results.json`, `ml/tagger/bench_clip.py` | `python ml/tagger/bench_clip.py` | 3.8 vs 29.4 ms/frame (7.7x), 9 MB vs 352 MB | done |
| Served by TensorFlow Serving (one server for the tagger and the re-ranker; `ml/tests` loads both SavedModels in CI) | `docker-compose.yml` (serving), `ml/serving/models.config`, `ml/tests/test_saved_models.py`, `ml/tagger/export.py`, `backend/lecturelens/tagger.py` | `docker compose up serving` | demo course (2,806 frames) tagged in 41 s | done |
| Experiments tracked in MLflow | `ml/tagger/train.py` (run params, metrics, sizes) | `mlflow ui` after training | | done |

## Pipeline

| Claim | Proof | Reproduce | Number | Status |
|---|---|---|---|---|
| Idempotent, retryable stages; a crash mid-pipeline resumes without redoing work | `backend/lecturelens/pipeline/{stages,jobs}.py`; `test_crash_mid_pipeline_resumes_without_redoing_work`, `test_stages_are_idempotent` | `cd backend && pytest tests/test_pipeline.py` | | done |
| Tests run on synthetic lectures generated during the build (rendered slides + synthesized speech) | `backend/tests/fixtures/lecture.py` | `cd backend && pytest tests/test_pipeline.py` | | done |
| Course vocabulary fixes terms like "Dijkstra" | `test_real_whisper_and_course_vocabulary` | `cd backend && pytest tests/test_pipeline.py -k vocabulary` | | done |
| Slide/whiteboard capture: scene detection, near-duplicate removal, OCR | `backend/lecturelens/pipeline/{media,dedup,ocr}.py`, `backend/tests/test_{media,dedup}.py` | `cd backend && pytest tests/test_media.py tests/test_dedup.py` | | done |
| Whole MIT 6.006 course processed | local demo DB | `python scripts/seed_demo.py --queue` | 21 lectures, 2,806 frames | done |
| Handles the videos people actually upload: mov, m4v, mkv (also with Opus audio), webm, a phone held upright, rotation metadata, 320x180, 1080p60 and a 2-second clip all finish with every slide captured | `backend/tests/test_formats.py` (10 cases through the whole pipeline) | `cd backend && pytest tests/test_formats.py` | 10 of 10 | done |
| mkv files are copied into mp4 or webm so every browser can play them (only audio mp4 can't hold is re-encoded); a video no browser can play fails with a plain reason instead of a broken player | `remux`, `browser_container` in `pipeline/media.py`, the mkv case in `test_formats.py` | `cd backend && pytest tests/test_formats.py -k mkv` | | done |
| Black bars are cropped before scene detection, so slides filmed on a phone in portrait aren't missed | `black_bars` in `pipeline/media.py`, the portrait case in `test_formats.py` | `cd backend && pytest tests/test_formats.py -k portrait` | | done |
| A video with no sound still works: searchable by its slides, and the transcript says nobody speaks | `test_silent_video_is_searchable_by_its_slides` | `cd backend && pytest tests/test_pipeline.py -k silent` | | done |
| Code in a screen recording is read: 18 px editor text at 1080p, dark and light themes | `test_ocr_reads_a_screen_recording_of_code` | `cd backend && pytest tests/test_media.py -k code` | over 90% of the names in the code | done |
| One frame stuck in OCR is skipped instead of failing the lecture | `test_ocr_timeout_skips_the_frame` | `cd backend && pytest tests/test_media.py -k timeout` | | done |
| A tagger outage doesn't fail a lecture | `test_tagging_survives_tf_serving_being_down` | `cd backend && pytest tests/test_pipeline.py -k serving` | | done |
| Speaker labels | | | | cut |

## Accounts, uploads and security

| Claim | Proof | Reproduce | Number | Status |
|---|---|---|---|---|
| Passwordless sign-in: email magic links and Google | `backend/lecturelens/auth.py`, `backend/tests/test_auth.py` | `cd backend && pytest tests/test_auth.py` | | done |
| Private by default; group checks on every route; another user's course looks like a 404 | `backend/lecturelens/access.py`, `backend/tests/test_access.py`, `backend/tests/test_uploads.py` | `cd backend && pytest tests/test_access.py` | | done |
| Resumable uploads on signed URLs (same protocol as Google Cloud Storage) | `backend/lecturelens/api/routes/uploads.py`, `test_chunked_upload_resumes_and_queues`; in the browser, `frontend/e2e/upload.spec.ts` kills a chunk's connection twice, cancels, resumes, and searches the result | `cd backend && pytest tests/test_uploads.py`; `scripts/e2e.sh` | | done (uploads go through the API; direct-to-storage is cut) |
| Uploading the same video twice lands on the first lecture instead of a copy (SHA-256 of the file, per course) | `test_same_video_twice_points_at_the_first_lecture`; end of the first test in `frontend/e2e/upload.spec.ts` | `cd backend && pytest tests/test_uploads.py -k same_video` | | done |
| A failed lecture can be retried or deleted from the UI | `POST /lectures/{id}/retry`, `test_retry_requeues_only_failed_lectures`, `test_corrupt_video_fails_fast_with_a_plain_error`; "bad files get a clear answer" in `frontend/e2e/upload.spec.ts` | `cd backend && pytest tests/test_lecture_admin.py`; `scripts/e2e.sh` | | done |
| YouTube import | `backend/lecturelens/pipeline/fetch.py`, `test_youtube_import`, `test_youtube_links` | `cd backend && pytest tests/test_uploads.py -k youtube` | | done. **The download is mocked in tests** (`test_youtube_import` swaps in a local file; the browser test uses a missing video id and checks the failure message). A real import runs only by hand: `.github/workflows/youtube.yml` |
| Live pipeline progress over server-sent events | `GET /lectures/{id}/events`, `test_progress_stream` | `cd backend && pytest tests/test_uploads.py -k progress` | | done |
| Live progress isn't held back by response compression (`Cache-Control: no-transform`) | `backend/lecturelens/api/routes/lectures.py`, header check in `test_progress_stream`; found by the browser tests | `cd backend && pytest tests/test_uploads.py -k progress` | | done |
| Media through signed URLs that expire after 15 minutes | `backend/lecturelens/api/routes/watch.py`, `test_media_links_expire_and_cant_be_forged` | `cd backend && pytest tests/test_watch.py` | 15 min | done |
| Upload type checked by its first bytes (not the file name), 4 GB limit | `looks_like_video` in `backend/lecturelens/pipeline/media.py`, `test_looks_like_video`, `test_non_video_is_refused_on_the_first_chunk`, `test_upload_rules`; `max_upload_bytes` in `config.py` | `cd backend && pytest tests/test_uploads.py` | 4 GB | done |
| Prompt-injection defense: transcript text is quoted data, uncited sentences are dropped | `backend/lecturelens/study/ask.py`, `test_injected_transcript_text_stays_data`, `test_claude_answer_keeps_only_cited_sentences`, `test_all_uncited_means_not_covered` | `cd backend && pytest tests/test_study.py` | | done |
| AI rate and token limits per user (per minute, day and month) | `backend/lecturelens/ai.py` (`guard`), `ai_calls` table, `test_ai_limits` | `cd backend && pytest tests/test_study.py -k limits` | 6/min, 200k tokens/day | done |
| API and worker containers run as a non-root user; the web app sends a content security policy | `backend/Dockerfile`, `frontend/Dockerfile` (`USER`), `headers()` in `frontend/next.config.ts`; `frontend/e2e/account.spec.ts` checks the header and fails on any console error (which is where CSP violations show up) | `scripts/e2e.sh` | | done |
| CodeQL (Python, TypeScript) and Trivy (dependencies, Dockerfiles, secrets) scan every push to main and weekly; findings go to the GitHub Security tab | `.github/workflows/security.yml` | Actions tab, Security workflow | | done |
| Bad input gets a 422 with a reason, never a 500: NUL bytes, half an emoji, NaN or Infinity, whitespace-only titles | exception handlers in `backend/lecturelens/api/main.py`, `backend/tests/test_inputs.py` | `cd backend && pytest tests/test_inputs.py` | | done |
| Sign-in links rate limited per address | `MAX_LIVE_LINKS` in `backend/lecturelens/auth.py`, `test_too_many_links_for_one_address` | `cd backend && pytest tests/test_auth.py` | 5 unused links per 15 min | done |
| Export / delete my data | | | | cut |

## Study and Ask

| Claim | Proof | Reproduce | Number | Status |
|---|---|---|---|---|
| Flashcards per lecture with SM-2 spaced repetition | `backend/lecturelens/study/srs.py`, `backend/tests/test_srs.py`, `test_review_schedules_the_card` | `cd backend && pytest tests/test_srs.py tests/test_study.py` | | done |
| Cards written by Claude when a key is set; without one, fill-in-the-blank cards from terms that were both said and shown on a slide | `backend/lecturelens/study/cards.py`, `test_claude_cards` (fake model), `test_cloze_cards_without_an_api_key` | `cd backend && pytest tests/test_study.py` | | done (the Claude path is tested with a fake model; CI has no API key) |
| Ask a lecture a question; every sentence of the answer cites a timestamp, and it says "not covered" instead of guessing | `backend/lecturelens/study/{retrieve,ask}.py`, `test_extractive_answer_quotes_the_lecture`, `test_all_uncited_means_not_covered` | `cd backend && pytest tests/test_study.py` | | done |

## Frontend and end-to-end tests

| Claim | Proof | Reproduce | Number | Status |
|---|---|---|---|---|
| Playwright clicks through every screen against the real stack (API, worker, Postgres, Redis, Next.js) and fails on any console error | `frontend/e2e/`, `scripts/e2e.sh`, `e2e` job in `.github/workflows/ci.yml` | `scripts/e2e.sh` | 17 tests, including a 390 px phone pass | done |
| Upload edge cases: dropped connection, cancel and resume, non-video, over the limit, cut-off file, retry | `frontend/e2e/upload.spec.ts` | `scripts/e2e.sh` | | done |

## Deployment

| Claim | Proof | Reproduce | Number | Status |
|---|---|---|---|---|
| One script sets up a fresh server: Docker, secrets, models, HTTPS through Caddy, the MIT lectures, and updates from `main` every 15 minutes | `deploy/bootstrap.sh`, `deploy/docker-compose.yml`, `deploy/Caddyfile`, `deploy/update.sh` | see "Deploy it" in the README | | done |
| Every change to the backend or deploy files starts the production stack on a fresh machine and checks it end to end over HTTPS (demo sign-in, upload, processing, search, playback) | `deploy/smoke.py`, `.github/workflows/deploy-check.yml` | `python3 deploy/smoke.py <site> <video> "<phrase>"` | | done |
| A public demo can't be run up: visitors get their own throwaway account, and uploads are capped per account and per day (deleting doesn't refund, and concurrent requests can't race past the cap) | `/auth/demo` in `backend/lecturelens/api/routes/auth.py`, `_daily_limit` in `lectures.py`, `test_demo_login_is_off_unless_enabled`, `test_daily_lecture_limit`, `test_site_wide_daily_limit`, `test_deleting_doesnt_reset_the_limit_and_racing_doesnt_beat_it` | `cd backend && pytest tests/test_auth.py tests/test_uploads.py` | 2 per account, 20 site-wide | done |

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
| A tagger outage doesn't fail a lecture | `test_tagging_survives_tf_serving_being_down` | `cd backend && pytest tests/test_pipeline.py -k serving` | | done |
| Speaker labels | | | | cut |

## Accounts, uploads and security

| Claim | Proof | Reproduce | Number | Status |
|---|---|---|---|---|
| Passwordless sign-in: email magic links and Google | `backend/lecturelens/auth.py`, `backend/tests/test_auth.py` | `cd backend && pytest tests/test_auth.py` | | done |
| Private by default; group checks on every route; another user's course looks like a 404 | `backend/lecturelens/access.py`, `backend/tests/test_access.py`, `backend/tests/test_uploads.py` | `cd backend && pytest tests/test_access.py` | | done |
| Resumable uploads on signed URLs (same protocol as Google Cloud Storage) | `backend/lecturelens/api/routes/uploads.py`, `test_chunked_upload_resumes_and_queues` | `cd backend && pytest tests/test_uploads.py` | | done (uploads go through the API; direct-to-storage is cut) |
| Uploading the same video twice lands on the first lecture instead of a copy (SHA-256 of the file, per course) | `test_same_video_twice_points_at_the_first_lecture` | `cd backend && pytest tests/test_uploads.py -k same_video` | | done |
| A failed lecture can be retried or deleted from the UI | `POST /lectures/{id}/retry`, `test_retry_requeues_only_failed_lectures`, `test_corrupt_video_fails_fast_with_a_plain_error`, the Try again and Delete buttons on the Upload screen | `cd backend && pytest tests/test_lecture_admin.py` | | done |
| YouTube import | `backend/lecturelens/pipeline/fetch.py`, `test_youtube_import`, `test_youtube_links` | `cd backend && pytest tests/test_uploads.py -k youtube` | | done. **The download is mocked in tests** (`test_youtube_import` swaps in a local file). A real import runs only by hand: `.github/workflows/youtube.yml` |
| Live pipeline progress over server-sent events | `GET /lectures/{id}/events`, `test_progress_stream` | `cd backend && pytest tests/test_uploads.py -k progress` | | done |
| Live progress isn't held back by response compression (`Cache-Control: no-transform`) | `backend/lecturelens/api/routes/lectures.py`, header check in `test_progress_stream`; found while testing in the browser | `cd backend && pytest tests/test_uploads.py -k progress` | | done |
| Media through signed URLs that expire after 15 minutes | `backend/lecturelens/api/routes/watch.py`, `test_media_links_expire_and_cant_be_forged` | `cd backend && pytest tests/test_watch.py` | 15 min | done |
| Upload type checked by its first bytes (not the file name), 4 GB limit | `looks_like_video` in `backend/lecturelens/pipeline/media.py`, `test_looks_like_video`, `test_non_video_is_refused_on_the_first_chunk`, `test_upload_rules`; `max_upload_bytes` in `config.py` | `cd backend && pytest tests/test_uploads.py` | 4 GB | done |
| Prompt-injection defense: transcript text is quoted data, uncited sentences are dropped | `backend/lecturelens/study/ask.py`, `test_injected_transcript_text_stays_data`, `test_claude_answer_keeps_only_cited_sentences`, `test_all_uncited_means_not_covered` | `cd backend && pytest tests/test_study.py` | | done |
| AI rate and token limits per user (per minute, day and month) | `backend/lecturelens/ai.py` (`guard`), `ai_calls` table, `test_ai_limits` | `cd backend && pytest tests/test_study.py -k limits` | 6/min, 200k tokens/day | done |
| API and worker containers run as a non-root user; the web app sends a content security policy | `backend/Dockerfile`, `frontend/Dockerfile` (`USER`), `headers()` in `frontend/next.config.ts` | `cd frontend && npm run build && npm start`, then check the response headers | | done |
| Sign-in links rate limited per address | `MAX_LIVE_LINKS` in `backend/lecturelens/auth.py`, `test_too_many_links_for_one_address` | `cd backend && pytest tests/test_auth.py` | 5 unused links per 15 min | done |
| Export / delete my data | | | | cut |

## Study and Ask

| Claim | Proof | Reproduce | Number | Status |
|---|---|---|---|---|
| Flashcards per lecture with SM-2 spaced repetition | `backend/lecturelens/study/srs.py`, `backend/tests/test_srs.py`, `test_review_schedules_the_card` | `cd backend && pytest tests/test_srs.py tests/test_study.py` | | done |
| Cards written by Claude when a key is set; without one, fill-in-the-blank cards from terms that were both said and shown on a slide | `backend/lecturelens/study/cards.py`, `test_claude_cards` (fake model), `test_cloze_cards_without_an_api_key` | `cd backend && pytest tests/test_study.py` | | done (the Claude path is tested with a fake model; CI has no API key) |
| Ask a lecture a question; every sentence of the answer cites a timestamp, and it says "not covered" instead of guessing | `backend/lecturelens/study/{retrieve,ask}.py`, `test_extractive_answer_quotes_the_lecture`, `test_all_uncited_means_not_covered` | `cd backend && pytest tests/test_study.py` | | done |

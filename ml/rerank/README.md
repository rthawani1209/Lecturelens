# Search re-ranker

Hybrid search merges four retrievers with reciprocal rank fusion (RRF), which only
looks at ranks. The re-ranker re-scores the top 50 fused candidates with a small
neural network that sees *why* each one was retrieved.

## Features (NumPy, `backend/lecturelens/search/features.py`)

25 per candidate window: keyword score, each retriever's RRF contribution, fused
score, MiniLM similarity of the query to the window and to its closest sentence,
CLIP similarity to the best frame, word overlap with the transcript and with the
slide text, tag match (the query says "code" / "board" / "diagram" and the frame
tagger agrees), the window's frame tags, position in the lecture, "first two
minutes", how many retrievers found it, and four relative ones (gap to the best
meaning and sentence match among the candidates, keyword share, meaning rank).

## Training data

- **Generated queries** (`build_dataset.py`): keyword-style queries made from the
  sentences and slide text of the 14 training lectures. Half of them drop their rarest
  word and 40% are wrapped in a question ("how does ... work"), so they don't just
  copy the window's own words. The window a query came from is the right answer.
  Lectures 1, 4, 7, 10, 13, 16 and 19 never produce training queries.
- **Hand-labeled questions** (`ml/eval/queries.jsonl`, 100 total): the 62 val
  questions are used for every choice (fusion weights, epoch, default mode). The 38
  test questions are only used for the final numbers.

## Model

`train.py`: a 25 → 32 → 16 → 1 network in Keras trained with a pairwise (RankNet)
loss: for a right and a wrong candidate of the same query, it learns to score the
right one higher. It re-scores the fused top 50 plus everything meaning search found.
The baseline is a scikit-learn logistic regression on the same features. Both log to
MLflow. The backend runs the same weights in NumPy, and a test checks they give the
same scores as Keras on fixed inputs. `export.py` rebuilds the SavedModel from
those committed weights into `models/reranker/1`, and docker-compose serves it next to
the tagger from one TF Serving (`ml/serving/models.config`). `ml/tests` checks the
served scores match within 1e-4.

## What was tried, chosen on val

1. **Fusion weights** (`ml/eval/tune_rrf.py`, `ml/eval/rrf_tuning_val.json`). A grid
   on val moved RRF from keyword 1.0 / ocr 0.8 / visual 0.6 to keyword 0.25 / ocr 0 /
   visual 0.3, which took hybrid from 0.672 to 0.748 NDCG@10 on val.
2. **Re-ranker inputs**: added meaning search's own top 50 to the pool, plus four
   features that compare a candidate to the others for the same query.
3. **Training queries**: the question templates and dropped words above. Twice as many
   generated queries (160 per lecture) scored lower on val (0.748), so 80 were kept.

Val NDCG@10: meaning-only 0.756, hybrid 0.748, hybrid + LR 0.710, hybrid + re-ranker
0.759. That is a tie (62 questions; 0.003 is one question moving a rank), so the
**default search is meaning-only**: same quality on val at about 1/13 of the latency
(about 20 ms vs 280 ms on the test run). The rule, fixed before looking at test: switch the default
only if a configuration beats meaning-only on val by at least 0.01.

## Results (38 held-out test questions, `ml/eval/results_test.json`)

| method | recall@5 | MRR | NDCG@10 | p50 |
|---|---|---|---|---|
| keyword only | 0.632 | 0.496 | 0.523 | 43 ms |
| hybrid, original weights (day 3) | 0.776 | 0.611 | 0.655 | 140 ms |
| hybrid, tuned weights | 0.816 | 0.684 | 0.719 | 128 ms |
| hybrid + logistic regression | 0.829 | 0.682 | 0.696 | 298 ms |
| hybrid + re-ranker | **0.882** | 0.675 | 0.720 | 280 ms |
| **meaning only (default)** | 0.855 | **0.779** | **0.786** | 21 ms |

What this shows, honestly:
- Two separate effects. Tuning the fusion weights on val took hybrid from 0.655 to
  0.719 NDCG@10 (recall@5 77.6% to 81.6%). The re-ranker then took recall@5 from 81.6%
  to 88.2%, the highest of any method, with NDCG@10 flat (0.719 to 0.720). It beats the
  logistic regression baseline (0.696).
- On this course, meaning-only search is the best single method, which is why it's
  the default. 6.006 is spoken explanation in front of a chalkboard, so slide text and
  CLIP add little, and generated queries still don't sound like real questions. Hybrid
  and the re-ranker are kept for courses with slides and code, where keyword and OCR
  matter more. Re-check this with a slide-heavy course before changing the default.

## Why the learned re-ranker didn't beat meaning-only

The likely cause is the training data, not the network. The re-ranker learned from
generated queries, and those are made from the window's own words, so they reward the
keyword and OCR features: "the answer contains my rare word" is almost always right
for them. Real student questions paraphrase ("why is the lower bound n log n?") and
rarely reuse the lecturer's exact words, which is the case meaning search already
handles best. So the model got very good at a slightly different task. The question
templates and dropped words narrowed the gap but didn't close it. The fix would be
real or paraphrased questions to train on (for example a few hundred hand-written
ones, or LLM paraphrases checked by hand), not a bigger network.

## Regression gate

`gate.py` (run in CI by `backend/tests/test_rerank.py`) fails if:
- the default search mode scores below any single retriever on the test questions,
- the re-ranker doesn't beat plain hybrid and the logistic regression,
- or a new re-ranker scores below the accepted one (`accepted.json`).

`--new-baseline` resets the comparison when the eval setup itself changes. It was
used once, on 2026-10-27, when the fusion weights and candidate pool changed.

## Reproduce

```bash
python ml/eval/tune_rrf.py                      # backend venv, val only
python ml/rerank/build_dataset.py              # needs the processed demo course
ml/.venv/bin/python ml/rerank/train.py
ml/.venv/bin/python ml/rerank/export.py          # SavedModel for TF Serving
python ml/eval/evaluate.py --split test --out ml/eval/results_test.json
python ml/rerank/gate.py --accept
```

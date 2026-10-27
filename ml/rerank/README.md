# Search re-ranker

Hybrid search merges four retrievers with reciprocal rank fusion (RRF), which only
looks at ranks. The re-ranker re-scores the top 50 fused candidates with a small
neural network that sees *why* each one was retrieved.

## Features (NumPy, `backend/lecturelens/search/features.py`)

21 per candidate window: keyword score, each retriever's RRF contribution, fused
score, MiniLM similarity of the query to the window and to its closest sentence,
CLIP similarity to the best frame, word overlap with the transcript and with the
slide text, tag match (the query says "code" / "board" / "diagram" and the frame
tagger agrees), the window's frame tags, position in the lecture, "first two
minutes" and how many retrievers found it.

## Training data

- **Generated queries** (`build_dataset.py`): 1,102 keyword-style queries made from
  sentences and slide text of the 14 training lectures. The window a query came from
  is the right answer. Lectures 1, 4, 7, 10, 13, 16 and 19 never produce training
  queries.
- **Hand-labeled questions** (`ml/eval/queries.jsonl`, 100 total): 62 val questions
  pick the epoch; 38 test questions are only used for the final numbers.

## Model

`train.py`: a 21 → 32 → 16 → 1 network in Keras trained with a pairwise (RankNet)
loss: for a right and a wrong candidate of the same query, it learns to score the
right one higher. The baseline is a scikit-learn logistic regression on the same
features. Both log to MLflow. The backend runs the same weights in NumPy, and a test
checks they give the same scores as Keras on fixed inputs. The SavedModel goes to
TF Serving.

## Results (38 held-out test questions, `ml/eval/results_test.json`)

| method | recall@5 | MRR | NDCG@10 |
|---|---|---|---|
| keyword only | 0.632 | 0.496 | 0.523 |
| hybrid (RRF) | 0.776 | 0.611 | 0.655 |
| hybrid + logistic regression | 0.803 | 0.647 | 0.675 |
| **hybrid + re-ranker** | **0.842** | **0.705** | **0.720** |
| meaning only (MiniLM) | 0.855 | 0.779 | 0.786 |

The re-ranker lifts hybrid search from 0.655 to 0.720 NDCG@10 and recall@5 from
77.6% to 84.2%, and it beats the logistic regression. The val split shows the same
order (0.672 → 0.748).

To be honest about it, meaning-only search is still the best single method on this
course. 6.006 is spoken explanation in front of a chalkboard: slide text and CLIP
add little, and the generated training queries are keyword-style, so they teach the
model to lean on keyword features. Training queries that paraphrase instead of
copying words are the obvious next step.

## Regression gate

`gate.py` refuses a new model unless, on the test questions, it beats plain hybrid
and the logistic regression and doesn't score below the accepted model
(`accepted.json`). CI runs it through `backend/tests/test_rerank.py`.

## Reproduce

```bash
python ml/rerank/build_dataset.py              # backend venv, needs the demo course
ml/.venv/bin/python ml/rerank/train.py
python ml/eval/evaluate.py --split test --out ml/eval/results_test.json
python ml/rerank/gate.py --accept
```

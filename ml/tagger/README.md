# Frame tagger

Tags every captured frame as **slide, code, whiteboard, diagram, professor** or **other**
(title cards, blank screens), so search can filter to "only whiteboard moments".

## How it's trained

1. **Teacher labels.** `pseudo_label.py` labels all 2,806 frames from the 21 MIT 6.006
   lectures using CLIP. Plain zero-shot prompts were only 67% right, so the teacher is a
   linear probe (softmax regression written in NumPy) on CLIP vectors, fit on
   hand-checked frames from the training lectures.
2. **Hand-checked set.** `contact_sheet.py` draws numbered grids of 300 frames
   (60 per CLIP label); each was labeled by eye into `data/hand_labels.csv`.
   Frames from lectures 1, 4, 7, 10, 13, 16 and 19 (the same held-out lectures as the
   search eval) are never trained on and form the test set (85 frames).
3. **Student.** `train.py` fine-tunes MobileNetV3-Small (ImageNet weights) in Keras on
   the teacher's soft labels: head only first, then the top 40 layers with BatchNorm
   frozen. Lectures 2 and 20 are used for early stopping. Runs log to MLflow.
4. **Export.** A SavedModel in TF Serving's `<name>/<version>/` layout under
   `models/tagger/`. `docker compose` serves it with `tensorflow/serving`; the worker
   calls its REST API. Without TF Serving, the backend falls back to the CLIP probe.

## Results (held-out lectures, 85 hand-checked frames, CPU)

| | accuracy | macro F1 | size | ms / frame (batch 32) |
|---|---|---|---|---|
| CLIP zero-shot | 67.1% | | 352 MB | 29.4 |
| CLIP + linear probe (teacher) | 83.5% | 0.66 | 352 MB | 29.4 |
| **MobileNetV3-Small (student)** | **83.5%** | **0.68** | **9 MB** | **3.8** |

The student matches its teacher at about 1/40 of the size and 8x the speed. Through TF
Serving's JSON REST API the whole 6.006 course (2,806 frames) is tagged in 135 s, and
the served model gives the same 83.5% on the test set.

Honest caveats:
- 6.006 is mostly chalkboard, so `code` has only 5 hand-checked examples; its score
  means little until a course with code on screen is added.
- whiteboard vs. diagram vs. professor is a judgment call on wide shots. Most errors are
  there, not on slides.

## Reproduce

```bash
python ml/tagger/pseudo_label.py      # backend venv; needs the processed demo course
python ml/tagger/contact_sheet.py     # optional: sheets for re-checking labels
uv venv ml/.venv && uv pip install --python ml/.venv/bin/python -r ml/requirements.txt
ml/.venv/bin/python ml/tagger/train.py
python ml/tagger/bench_clip.py        # CLIP timing for the table
```

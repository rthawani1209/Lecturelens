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
4. **Export.** `export.py` wraps the trained model for TF Serving (`models/tagger/<version>/`):
   the default signature takes JPEG bytes and resizes in the graph, and `tags.json` ships
   alongside so the backend can refuse a model whose output order doesn't match its tag
   names. `docker compose` serves it with `tensorflow/serving`; `scripts/get_models.sh`
   downloads it from the `tagger-v1` release. If TF Serving is missing or erroring, the
   worker logs a warning and tags with the CLIP probe instead of failing the lecture.

## Results (held-out lectures, 85 hand-checked frames, CPU)

| | accuracy | macro F1 | size | ms / frame (batch 32) |
|---|---|---|---|---|
| CLIP zero-shot | 67.1% | | 352 MB | 29.4 |
| CLIP + linear probe (teacher) | 83.5% | 0.66 | 352 MB | 29.4 |
| **MobileNetV3-Small (student)** | **83.5%** | **0.68** | **9 MB** | **3.8** |

The student matches its teacher at about 1/40 of the size and 8x the speed.

Serving: the first version took raw 224x224x3 pixel arrays, which is ~600 KB of JSON per
frame, and tagging the whole course (2,806 frames) through TF Serving took 135 s. Sending
the JPEG thumbnails as base64 (~20 KB) and resizing inside the graph cut that to 41 s.
Resizing in TF instead of PIL flips one test frame, so the served model scores 82.4%.

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
ml/.venv/bin/python ml/tagger/export.py models/tagger_build/<version>
python ml/tagger/bench_clip.py        # CLIP timing for the table
```

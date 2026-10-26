"""Draw numbered grids of frames so a person can check labels by eye.

    python ml/tagger/contact_sheet.py --per-tag 60 --out ml/tagger/data/sheets
writes sheet_XX.png plus sample.csv (the frames on the sheets, in order).
"""

import argparse
import csv
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

COLS, ROWS, W, H = 6, 5, 256, 144


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", type=Path, default=Path("ml/tagger/data/pseudo_labels.csv"))
    ap.add_argument("--storage", type=Path, default=Path("data/storage"))
    ap.add_argument("--per-tag", type=int, default=60)
    ap.add_argument("--out", type=Path, default=Path("ml/tagger/data/sheets"))
    ap.add_argument("--seed", type=int, default=6006)
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.labels)))
    rng = random.Random(args.seed)
    by_tag: dict[str, list[dict]] = {}
    for r in rows:
        by_tag.setdefault(r["label"], []).append(r)
    sample = []
    for tag in sorted(by_tag):
        sample += rng.sample(by_tag[tag], min(args.per_tag, len(by_tag[tag])))

    args.out.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype("DejaVuSans-Bold.ttf", 22)
    per_sheet = COLS * ROWS
    for s in range(0, len(sample), per_sheet):
        sheet = Image.new("RGB", (COLS * W, ROWS * H), "white")
        draw = ImageDraw.Draw(sheet)
        for i, r in enumerate(sample[s : s + per_sheet]):
            im = Image.open(args.storage / r["thumb_key"]).convert("RGB").resize((W - 4, H - 4))
            x, y = (i % COLS) * W, (i // COLS) * H
            sheet.paste(im, (x + 2, y + 2))
            draw.rectangle((x + 2, y + 2, x + 120, y + 30), fill="black")
            draw.text((x + 6, y + 4), f"{s + i} {r['label'][:4]}", fill="yellow", font=font)
        sheet.save(args.out / f"sheet_{s // per_sheet:02d}.png")
    with open(args.out / "sample.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["n", "frame_id", "thumb_key", "clip_label"])
        w.writeheader()
        for n, r in enumerate(sample):
            w.writerow(
                {
                    "n": n,
                    "frame_id": r["frame_id"],
                    "thumb_key": r["thumb_key"],
                    "clip_label": r["label"],
                }
            )
    print(f"{len(sample)} frames on {(len(sample) + per_sheet - 1) // per_sheet} sheets")


if __name__ == "__main__":
    main()

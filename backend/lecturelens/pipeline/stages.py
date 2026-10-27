"""The processing pipeline, one function per stage.

Each stage pulls its inputs from blob storage into a scratch dir and writes its
outputs back to storage + Postgres, so stages can run on different machines and
any of them can be retried on its own.
"""

import logging
import tempfile
import traceback
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import httpx
import numpy as np

from ..config import get_settings
from ..db import connection
from ..storage import get_storage
from . import jobs
from .chunk import Sentence, windows
from .dedup import dedupe, dhash, signature, to_signed
from .fetch import download_youtube
from .media import MediaError, extract_audio, keyframes, probe
from .ocr import ocr
from .transcribe import transcribe

log = logging.getLogger(__name__)

Progress = Callable[[float], None]


def _key(lecture_id: UUID, name: str) -> str:
    return f"lectures/{lecture_id}/{name}"


def _lecture(lecture_id: UUID) -> dict:
    with connection() as conn:
        row = conn.execute(
            "SELECT l.*, c.id AS course_id FROM lectures l JOIN courses c ON c.id = l.course_id"
            " WHERE l.id = %s",
            (lecture_id,),
        ).fetchone()
    if row is None:
        raise LookupError(f"lecture {lecture_id} not found")
    return row


def _video(lecture: dict, work: Path) -> Path:
    if not lecture["storage_key"]:
        raise MediaError("lecture has no uploaded video")
    return get_storage().get_file(lecture["storage_key"], work / "video")


def stage_fetch(lecture_id: UUID, work: Path, report: Progress) -> None:
    """Imported lectures start as a URL; download it so the rest looks like an upload."""
    lecture = _lecture(lecture_id)
    if lecture["storage_key"]:
        return
    if not lecture["source_url"]:
        raise MediaError("lecture has no uploaded video")
    video, title = download_youtube(lecture["source_url"], work, get_settings().max_upload_bytes)
    key = _key(lecture_id, f"source{video.suffix}")
    get_storage().put_file(key, video)
    with connection() as conn:
        conn.execute(
            "UPDATE lectures SET storage_key = %s,"
            " title = CASE WHEN title = '' THEN %s ELSE title END WHERE id = %s",
            (key, title[:200] or "Untitled lecture", lecture_id),
        )


def stage_probe(lecture_id: UUID, work: Path, report: Progress) -> None:
    info = probe(_video(_lecture(lecture_id), work))
    if not (info["has_video"] and info["has_audio"]):
        raise MediaError("file needs both a video and an audio track")
    with connection() as conn:
        conn.execute(
            "UPDATE lectures SET duration_s = %s WHERE id = %s", (info["duration_s"], lecture_id)
        )


def stage_audio(lecture_id: UUID, work: Path, report: Progress) -> None:
    wav = extract_audio(_video(_lecture(lecture_id), work), work / "audio.wav")
    get_storage().put_file(_key(lecture_id, "audio.wav"), wav)


def stage_transcribe(lecture_id: UUID, work: Path, report: Progress) -> None:
    lecture = _lecture(lecture_id)
    wav = get_storage().get_file(_key(lecture_id, "audio.wav"), work / "audio.wav")
    with connection() as conn:
        terms = [
            r["term"]
            for r in conn.execute(
                "SELECT term FROM course_terms WHERE course_id = %s", (lecture["course_id"],)
            )
        ]
    model_dir = Path(get_settings().models_dir) / "whisper"
    sentences = transcribe(wav, model_dir, terms, on_progress=report)
    save_transcript(lecture_id, sentences)


def save_transcript(lecture_id: UUID, sentences: list[Sentence]) -> None:
    """Replace the lecture's transcript and search windows in one transaction."""
    wins = windows(sentences)
    with connection() as conn, conn.transaction():
        conn.execute("DELETE FROM transcript_lines WHERE lecture_id = %s", (lecture_id,))
        conn.execute("DELETE FROM segments WHERE lecture_id = %s", (lecture_id,))
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO transcript_lines (lecture_id, start_s, end_s, text)"
                " VALUES (%s, %s, %s, %s)",
                [(lecture_id, s.start_s, s.end_s, s.text) for s in sentences],
            )
            cur.executemany(
                "INSERT INTO segments (lecture_id, start_s, end_s, text) VALUES (%s, %s, %s, %s)",
                [(lecture_id, w.start_s, w.end_s, w.text) for w in wins],
            )


def stage_frames(lecture_id: UUID, work: Path, report: Progress) -> None:
    shots = keyframes(_video(_lecture(lecture_id), work), work / "frames")
    hashes = [dhash(k.path) for k in shots]
    keep = dedupe([signature(k.path) for k in shots])
    storage = get_storage()
    rows = []
    for n, i in enumerate(keep):
        key = _key(lecture_id, f"frames/{int(shots[i].t_s * 1000):08d}.jpg")
        storage.put_file(key, shots[i].path)
        rows.append((lecture_id, shots[i].t_s, key, to_signed(hashes[i])))
        report((n + 1) / len(keep))
    with connection() as conn, conn.transaction():
        conn.execute("DELETE FROM frames WHERE lecture_id = %s", (lecture_id,))
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO frames (lecture_id, t_s, thumb_key, phash) VALUES (%s, %s, %s, %s)",
                rows,
            )


def stage_ocr(lecture_id: UUID, work: Path, report: Progress) -> None:
    with connection() as conn:
        frames = conn.execute(
            "SELECT id, thumb_key FROM frames WHERE lecture_id = %s ORDER BY t_s", (lecture_id,)
        ).fetchall()
    storage = get_storage()
    updates = []
    for n, f in enumerate(frames):
        img = storage.get_file(f["thumb_key"], work / "ocr" / f"{f['id']}.jpg")
        updates.append((ocr(img), f["id"]))
        report((n + 1) / len(frames))
    with connection() as conn, conn.cursor() as cur:
        cur.executemany("UPDATE frames SET ocr_text = %s WHERE id = %s", updates)


def stage_embed_text(lecture_id: UUID, work: Path, report: Progress) -> None:
    from ..embed import text_embedder

    with connection() as conn:
        segs = conn.execute(
            "SELECT id, text FROM segments WHERE lecture_id = %s ORDER BY start_s", (lecture_id,)
        ).fetchall()
        lines = conn.execute(
            "SELECT id, text FROM transcript_lines WHERE lecture_id = %s", (lecture_id,)
        ).fetchall()
    emb = text_embedder()
    seg_vecs = emb.embed([s["text"] for s in segs])
    report(0.5)
    line_vecs = emb.embed([x["text"] for x in lines])
    report(1.0)
    with connection() as conn, conn.cursor() as cur:
        cur.executemany(
            "UPDATE segments SET text_emb = %s WHERE id = %s",
            [(v, s["id"]) for v, s in zip(seg_vecs, segs, strict=True)],
        )
        cur.executemany(
            "UPDATE transcript_lines SET text_emb = %s WHERE id = %s",
            [(v, x["id"]) for v, x in zip(line_vecs, lines, strict=True)],
        )


def stage_embed_frames(lecture_id: UUID, work: Path, report: Progress) -> None:
    from ..embed import clip_embedder

    with connection() as conn:
        frames = conn.execute(
            "SELECT id, thumb_key FROM frames WHERE lecture_id = %s ORDER BY t_s", (lecture_id,)
        ).fetchall()
    if not frames:
        return
    storage = get_storage()
    paths = [storage.get_file(f["thumb_key"], work / f"{f['id']}.jpg") for f in frames]
    vecs = clip_embedder().embed_images(paths)
    report(1.0)
    with connection() as conn, conn.cursor() as cur:
        cur.executemany(
            "UPDATE frames SET clip_emb = %s WHERE id = %s",
            [(v, f["id"]) for v, f in zip(vecs, frames, strict=True)],
        )


def stage_tag(lecture_id: UUID, work: Path, report: Progress) -> None:
    import json

    from .. import tagger

    with connection() as conn:
        frames = conn.execute(
            "SELECT id, thumb_key, clip_emb FROM frames WHERE lecture_id = %s ORDER BY t_s",
            (lecture_id,),
        ).fetchall()
    if not frames:
        return
    scores = None
    if url := tagger.tagger_url():
        storage = get_storage()
        paths = [storage.get_file(f["thumb_key"], work / f"{f['id']}.jpg") for f in frames]
        try:
            scores = tagger.serving_scores(paths, url)
        except (httpx.HTTPError, OSError, ValueError, tagger.TagOrderError) as e:
            # tags are nice to have; a down tagger shouldn't fail the whole lecture
            log.warning("tagger at %s failed (%s), using the CLIP probe", url, e)
    if scores is None:
        scores = tagger.probe_scores(np.stack([f["clip_emb"].to_numpy() for f in frames]))
    report(1.0)
    names = tagger.tags()
    with connection() as conn, conn.cursor() as cur:
        cur.executemany(
            "UPDATE frames SET tag = %s, tag_scores = %s WHERE id = %s",
            [
                (
                    names[int(s.argmax())],
                    json.dumps({n: round(float(x), 4) for n, x in zip(names, s, strict=True)}),
                    f["id"],
                )
                for s, f in zip(scores, frames, strict=True)
            ],
        )


STAGES: list[tuple[str, Callable[[UUID, Path, Progress], None]]] = [
    ("fetch", stage_fetch),
    ("probe", stage_probe),
    ("audio", stage_audio),
    ("transcribe", stage_transcribe),
    ("frames", stage_frames),
    ("ocr", stage_ocr),
    ("embed_text", stage_embed_text),
    ("embed_frames", stage_embed_frames),
    ("tag", stage_tag),
]


def run_stage(lecture_id: UUID, name: str) -> None:
    fn = dict(STAGES)[name]
    jobs.start(lecture_id, name)
    try:
        with tempfile.TemporaryDirectory(prefix=f"ll-{name}-") as tmp:
            fn(lecture_id, Path(tmp), jobs.progress_reporter(lecture_id, name))
    except Exception as e:
        log.exception("stage %s failed for %s", name, lecture_id)
        jobs.fail(lecture_id, name, f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}")
        raise
    jobs.finish(lecture_id, name)
    if jobs.done_stages(lecture_id) >= {n for n, _ in STAGES}:
        with connection() as conn:
            conn.execute("UPDATE lectures SET status = 'ready' WHERE id = %s", (lecture_id,))


def run_pipeline(lecture_id: UUID, only: list[str] | None = None) -> None:
    """Run every stage that isn't done yet, in order. Safe to call again after a crash."""
    done = jobs.done_stages(lecture_id)
    for name, _ in STAGES:
        if only and name not in only:
            continue
        if name not in done:
            run_stage(lecture_id, name)

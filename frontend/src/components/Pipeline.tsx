"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ApiError, api, type LectureDetail } from "@/lib/api";
import styles from "./Upload.module.css";

const ABOUT: Record<string, [string, string]> = {
  fetch: ["Fetch", "Get the video"],
  probe: ["Probe", "Length and format"],
  audio: ["Audio", "Extract speech"],
  transcribe: ["Transcribe", "Whisper, with course words"],
  frames: ["Frames", "Scene cuts, drop duplicates"],
  ocr: ["OCR", "Read boards and slides"],
  embed_text: ["Embed text", "Meaning vectors"],
  embed_frames: ["Embed frames", "CLIP image vectors"],
  tag: ["Tag", "Slide, board, code…"],
};

/** Live view of one lecture going through the pipeline, over server-sent events. */
export function Pipeline({ id, onDeleted }: { id: string; onDeleted: () => void }) {
  const [lec, setLec] = useState<LectureDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [retryNote, setRetryNote] = useState<string | null>(null);

  useEffect(() => {
    let closed = false;
    api.lecture(id).then(setLec, (e: Error) => setError(e.message));
    const es = new EventSource(`/api/lectures/${id}/events`);
    es.addEventListener("progress", (e) => setLec(JSON.parse((e as MessageEvent).data)));
    es.addEventListener("gone", () => {
      es.close();
      setError("This lecture was deleted.");
    });
    // the stream ends when the lecture is ready or failed; fetch once more to be sure
    es.onerror = () => {
      es.close();
      if (!closed) api.lecture(id).then(setLec, () => undefined);
    };
    return () => {
      closed = true;
      es.close();
    };
  }, [id, attempt]);

  async function retry() {
    setBusy(true);
    setRetryNote(null);
    try {
      setLec(await api.retry(id));
      setAttempt((n) => n + 1);
    } catch (e) {
      // 409 on a lecture that's queued or processing: it's still moving
      setRetryNote(
        e instanceof ApiError && e.status === 409
          ? "It's still being worked on. Give it a few more minutes."
          : (e as Error).message,
      );
    } finally {
      setBusy(false);
    }
  }

  if (error) return <p className={styles.error}>{error}</p>;
  if (!lec) return <div className={styles.pipeSkeleton} aria-busy="true" />;

  const failed = lec.status === "failed";
  const firstError = lec.stages.find((s) => s.error)?.error;
  const running = lec.stages.find((s) => s.status === "running");

  return (
    <section className={styles.pipe} aria-label="Processing">
      <div className={styles.pipeHead}>
        <div>
          <h2>{lec.title}</h2>
          <span className="mono">
            {lec.status === "ready"
              ? "Ready: searchable, with transcript, frames and tags"
              : failed
                ? "Stopped"
                : "You can leave this page; it keeps going"}
          </span>
        </div>
        <span className={`mono ${styles.state} ${styles[`state_${lec.status}`] ?? ""}`}>
          {lec.status === "ready"
            ? "✓ ready"
            : failed
              ? "failed"
              : `● ${Math.round(lec.progress * 100)}%`}
        </span>
      </div>

      <ol className={styles.stages}>
        {lec.stages.map((s, i) => {
          const [label, what] = ABOUT[s.stage] ?? [s.stage, ""];
          return (
            <li key={s.stage} className={styles[`stage_${s.status}`]}>
              <span className="mono">{String(i + 1).padStart(2, "0")}</span>
              <strong>{label}</strong>
              <span>{what}</span>
              <span className={`mono ${styles.stageState}`}>
                {s.status === "done"
                  ? "✓ done"
                  : s.status === "running"
                    ? `● ${Math.round(s.progress * 100)}%`
                    : s.status}
              </span>
              <span
                className={styles.bar}
                style={{ width: `${(s.status === "done" ? 1 : s.progress) * 100}%` }}
                aria-hidden="true"
              />
            </li>
          );
        })}
      </ol>

      {running && (
        <p className={`mono ${styles.now}`} aria-live="polite">
          Now: {ABOUT[running.stage]?.[0] ?? running.stage}
        </p>
      )}

      {failed && (
        <div className={styles.failBox} role="alert">
          <p>{firstError ?? "Processing stopped."}</p>
          <div>
            <button type="button" className={styles.primary} disabled={busy} onClick={retry}>
              Try again
            </button>
            {confirming ? (
              <button
                type="button"
                className={styles.danger}
                onClick={async () => {
                  await api.deleteLecture(id);
                  onDeleted();
                }}
              >
                Yes, delete it
              </button>
            ) : (
              <button
                type="button"
                className={styles.secondary}
                onClick={() => setConfirming(true)}
              >
                Delete
              </button>
            )}
          </div>
        </div>
      )}

      {(lec.status === "queued" || lec.status === "processing") && (
        // a lecture with no progress for an hour can be put back in line
        <p className={`mono ${styles.now}`}>
          Stuck?{" "}
          <button type="button" className={styles.link} disabled={busy} onClick={retry}>
            Try again
          </button>
        </p>
      )}
      {retryNote && (
        <p className={styles.error} role="status">
          {retryNote}
        </p>
      )}

      {lec.status === "ready" && (
        <div className={styles.doneRow}>
          <Link href={`/watch/${lec.id}`} className={styles.primary}>
            Watch it
          </Link>
          <Link href={`/search?course=${lec.course_id}`} className={styles.secondary}>
            Search the course
          </Link>
        </div>
      )}
    </section>
  );
}

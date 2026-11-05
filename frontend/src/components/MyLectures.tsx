"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, type Lecture } from "@/lib/api";
import { timecode } from "@/lib/format";
import styles from "./Upload.module.css";

const STATE: Record<string, string> = {
  queued: "queued",
  processing: "processing",
  ready: "✓ ready",
  failed: "failed",
};

/** Every lecture in one of your courses, with retry and delete for the ones that need it. */
export function MyLectures({
  courseId,
  current,
  onOpen,
}: {
  courseId: string;
  current: string | null;
  onOpen: (id: string | null) => void;
}) {
  const [lectures, setLectures] = useState<Lecture[] | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    () =>
      api.lectures(courseId).then(
        (ls) => setLectures([...ls].sort((a, b) => a.position - b.position)),
        (e: Error) => setError(e.message),
      ),
    [courseId],
  );

  // reload when the lecture shown above changes (a new upload, a delete)
  useEffect(() => {
    setConfirming(null);
    load();
  }, [load, current]);

  // keep statuses fresh while anything is still being processed
  const working = lectures?.some((l) => l.status === "queued" || l.status === "processing");
  useEffect(() => {
    if (!working) return;
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [working, load]);

  if (!lectures?.length) return null;

  return (
    <section className={styles.mine} aria-labelledby="mine-title">
      <h2 id="mine-title">Your lectures</h2>
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      <ul>
        {lectures.map((l) => (
          <li key={l.id} className={l.id === current ? styles.mineOn : undefined}>
            <span className={`mono ${styles.mineMeta}`}>L{l.position}</span>
            <span className={styles.mineTitle}>{l.title}</span>
            <span className={`mono ${styles.mineMeta}`}>
              {l.duration_s ? timecode(l.duration_s) : "–"}
            </span>
            <span className={`mono ${styles.minePill} ${styles[`pill_${l.status}`] ?? ""}`}>
              {STATE[l.status] ?? l.status}
            </span>
            <span className={styles.mineActions}>
              {l.status === "ready" && (
                <Link className={styles.secondary} href={`/watch/${l.id}`}>
                  Watch
                </Link>
              )}
              {l.status !== "ready" && l.id !== current && (
                <button type="button" className={styles.secondary} onClick={() => onOpen(l.id)}>
                  Details
                </button>
              )}
              {l.status === "failed" && (
                <button
                  type="button"
                  className={styles.secondary}
                  onClick={async () => {
                    setError(null);
                    try {
                      await api.retry(l.id);
                      onOpen(l.id);
                      load();
                    } catch (e) {
                      setError(e instanceof Error ? e.message : "Couldn't retry.");
                    }
                  }}
                >
                  Try again
                </button>
              )}
              {confirming === l.id ? (
                <button
                  type="button"
                  className={styles.danger}
                  onClick={async () => {
                    setError(null);
                    try {
                      await api.deleteLecture(l.id);
                      if (l.id === current) onOpen(null);
                      setConfirming(null);
                      load();
                    } catch (e) {
                      setError(e instanceof Error ? e.message : "Couldn't delete.");
                    }
                  }}
                >
                  Yes, delete it
                </button>
              ) : (
                <button
                  type="button"
                  className={styles.secondary}
                  aria-label={`Delete ${l.title}`}
                  onClick={() => setConfirming(l.id)}
                >
                  Delete
                </button>
              )}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

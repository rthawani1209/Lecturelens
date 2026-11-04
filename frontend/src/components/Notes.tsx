"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ApiError, api, type Note } from "@/lib/api";
import { timecode } from "@/lib/format";
import styles from "./Watch.module.css";

export function Notes({
  lectureId,
  time,
  onSeek,
}: {
  lectureId: string;
  time: number;
  onSeek: (t: number) => void;
}) {
  const [notes, setNotes] = useState<Note[] | "signed-out" | null>(null);
  const [draft, setDraft] = useState("");
  const [at, setAt] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    // ask who's signed in first, so signed-out viewers don't trigger a 401
    api
      .me()
      .then((me) => (me ? api.notes(lectureId).then(setNotes) : setNotes("signed-out")))
      .catch((e) => setNotes(e instanceof ApiError && e.status === 401 ? "signed-out" : []));
  }, [lectureId]);

  // N starts a note at the current moment
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const el = e.target as HTMLElement;
      if (["INPUT", "TEXTAREA"].includes(el.tagName) || e.metaKey || e.ctrlKey) return;
      if (e.key.toLowerCase() === "n" && Array.isArray(notes)) {
        e.preventDefault();
        setAt(time);
        box.current?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [notes, time]);

  if (notes === "signed-out") {
    return (
      <section className={styles.panel} aria-label="Your notes">
        <h2 className="label">Your notes</h2>
        <p className={styles.muted}>
          <Link href={`/signin?next=/watch/${lectureId}`}>Sign in</Link> to keep notes pinned to
          moments in the lecture.
        </p>
      </section>
    );
  }

  const stamp = at ?? time;

  return (
    <section className={styles.panel} aria-label="Your notes">
      <h2 className="label">Your notes</h2>
      <ul className={styles.notes}>
        {notes?.length === 0 && <li className={styles.muted}>No notes yet. Press N to add one.</li>}
        {Array.isArray(notes) &&
          notes.map((n) => (
            <li key={n.id}>
              <button type="button" className={`mono ${styles.link}`} onClick={() => onSeek(n.t_s)}>
                {timecode(n.t_s)}
              </button>
              <span>{n.text}</span>
              <button
                type="button"
                className={styles.remove}
                aria-label={`Delete note at ${timecode(n.t_s)}`}
                onClick={async () => {
                  await api.deleteNote(n.id).catch(() => undefined);
                  setNotes((all) => (Array.isArray(all) ? all.filter((x) => x.id !== n.id) : all));
                }}
              >
                ×
              </button>
            </li>
          ))}
      </ul>
      <form
        className={styles.noteForm}
        onSubmit={async (e) => {
          e.preventDefault();
          if (!draft.trim()) return;
          try {
            const n = await api.addNote(lectureId, stamp, draft.trim());
            setNotes((all) =>
              Array.isArray(all) ? [...all, n].sort((a, b) => a.t_s - b.t_s) : [n],
            );
            setDraft("");
            setAt(null);
            setError(null);
          } catch (err) {
            setError((err as Error).message);
          }
        }}
      >
        <label htmlFor="note" className="sr-only">
          Note at {timecode(stamp)}
        </label>
        <textarea
          id="note"
          ref={box}
          rows={2}
          maxLength={2000}
          value={draft}
          onFocus={() => setAt((a) => a ?? time)}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={`Note at ${timecode(stamp)}`}
        />
        {error && (
          <p className={styles.error} role="alert">
            {error}
          </p>
        )}
        <button type="submit" className={styles.secondary} disabled={!draft.trim()}>
          Save note at {timecode(stamp)}
        </button>
      </form>
    </section>
  );
}

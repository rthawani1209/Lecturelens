"use client";

import Link from "next/link";
import { useState } from "react";
import { api, type Answer } from "@/lib/api";
import { timecode } from "@/lib/format";
import styles from "./Study.module.css";

/** Ask a question about one lecture; the answer cites the moments it came from. */
export function AskBox({ lectureId, courseId }: { lectureId: string; courseId: string }) {
  const [q, setQ] = useState("");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [asked, setAsked] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const question = q.trim();
    if (question.length < 2) return;
    setBusy(true);
    setError(null);
    try {
      setAnswer(await api.ask(lectureId, question));
      setAsked(question);
    } catch (err) {
      setAnswer(null);
      setError(err instanceof Error ? err.message : "Couldn't ask right now.");
    } finally {
      setBusy(false);
    }
  }

  const time = (n: number) => answer?.sources.find((s) => s.n === n)?.start_s ?? 0;

  return (
    <form className={styles.ask} onSubmit={submit}>
      <label htmlFor="ask" className="label">
        Ask about this lecture
      </label>
      <div className={styles.askRow}>
        <input
          id="ask"
          type="text"
          maxLength={500}
          placeholder="e.g. why is decrease_key needed at all?"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <button type="submit" disabled={busy || q.trim().length < 2}>
          {busy ? "Asking…" : "Ask"}
        </button>
      </div>
      <p className={styles.hint}>
        Answers quote the lecture with timestamps, and say so when it isn&apos;t covered.
      </p>

      {error && (
        <p className={styles.askError} role="alert">
          {error}
        </p>
      )}

      {answer && (
        <div className={styles.answer} aria-live="polite">
          <p className="label">
            {answer.covered
              ? answer.mode === "claude"
                ? "Answer · from this lecture"
                : "Quoted from the lecture"
              : "Not covered"}
            <span className={styles.askedQ}> · {asked}</span>
          </p>
          {answer.covered ? (
            <>
              <p className={styles.answerText}>
                {answer.sentences.map((s, i) => (
                  <span key={i}>
                    {answer.mode === "extractive" ? `“${s.text}”` : s.text}
                    {s.cites.map((n) => (
                      <Link
                        key={n}
                        className={`mono ${styles.cite}`}
                        href={`/watch/${lectureId}?t=${Math.floor(time(n))}`}
                        title={`Watch at ${timecode(time(n))}`}
                      >
                        {timecode(time(n))}
                      </Link>
                    ))}{" "}
                  </span>
                ))}
              </p>
            </>
          ) : (
            <p className={styles.answerText}>
              This lecture doesn&apos;t seem to cover that.{" "}
              <Link href={`/search?q=${encodeURIComponent(asked)}&course=${courseId}`}>
                Search the whole course
              </Link>{" "}
              instead.
            </p>
          )}
        </div>
      )}
    </form>
  );
}

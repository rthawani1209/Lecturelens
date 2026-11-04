"use client";

import { useEffect, useRef, useState } from "react";
import type { Mode } from "@/lib/api";
import styles from "./Search.module.css";

export const MODES: { id: Mode; label: string; note: string }[] = [
  {
    id: "meaning",
    label: "Meaning",
    note: "Meaning search · the default: it was the most accurate on held-out lectures",
  },
  {
    id: "hybrid",
    label: "Hybrid",
    note: "Hybrid · keyword + meaning + slide text + visual, re-ranked by a small learned model",
  },
  { id: "keyword", label: "Keyword", note: "Keyword · exact words in the transcript" },
];

type Props = {
  initial?: string;
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  onSubmit: (q: string) => void;
  autoFocus?: boolean;
};

export function SearchBox({ initial = "", mode, onModeChange, onSubmit, autoFocus }: Props) {
  const [q, setQ] = useState(initial);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => setQ(initial), [initial]);

  // "/" jumps to the search box from anywhere on the page
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const el = e.target as HTMLElement;
      if (e.key === "/" && !["INPUT", "TEXTAREA"].includes(el.tagName)) {
        e.preventDefault();
        input.current?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div>
      <form
        role="search"
        className={styles.box}
        onSubmit={(e) => {
          e.preventDefault();
          if (q.trim()) onSubmit(q.trim());
        }}
      >
        <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true" className={styles.glass}>
          <circle cx="10.5" cy="10.5" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
          <path
            d="M15.5 15.5 21 21"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
          />
        </svg>
        <label htmlFor="q" className="sr-only">
          Ask the course
        </label>
        <input
          id="q"
          ref={input}
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Ask anything: “why can't Dijkstra handle negative weights?”"
          autoFocus={autoFocus}
          autoComplete="off"
          maxLength={300}
          className={styles.input}
        />
        <div role="group" aria-label="Search mode" className={styles.modes}>
          {MODES.map((m) => (
            <button
              key={m.id}
              type="button"
              aria-pressed={mode === m.id}
              className={mode === m.id ? `${styles.mode} ${styles.modeOn}` : styles.mode}
              onClick={() => onModeChange(m.id)}
            >
              {m.label}
            </button>
          ))}
        </div>
        <button type="submit" className={styles.go} aria-label="Search">
          <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
            <path
              d="M5 12h13M13 6l6 6-6 6"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
      </form>
      <p className={`mono ${styles.note}`}>{MODES.find((m) => m.id === mode)?.note}</p>
    </div>
  );
}

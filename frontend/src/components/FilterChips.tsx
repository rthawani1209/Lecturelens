"use client";

import type { Tag } from "@/lib/api";
import styles from "./Search.module.css";

export const TAGS: { id: Tag | "all"; label: string; color: string }[] = [
  { id: "all", label: "All frames", color: "var(--muted)" },
  { id: "slide", label: "Slides", color: "var(--ch-ocr)" },
  { id: "code", label: "Code", color: "var(--ch-visual)" },
  { id: "whiteboard", label: "Whiteboard", color: "var(--text)" },
  { id: "diagram", label: "Diagram", color: "var(--ch-meaning)" },
  { id: "professor", label: "Professor", color: "var(--ch-keyword)" },
];

export function FilterChips({
  value,
  onChange,
}: {
  value: Tag | "all";
  onChange: (tag: Tag | "all") => void;
}) {
  return (
    <div role="group" aria-label="What's on screen" className={styles.chips}>
      {TAGS.map((t, i) => (
        <button
          key={t.id}
          type="button"
          aria-pressed={value === t.id}
          aria-keyshortcuts={String(i + 1)}
          className={value === t.id ? `${styles.chip} ${styles.chipOn}` : styles.chip}
          onClick={() => onChange(t.id)}
        >
          <span className={styles.swatch} style={{ background: t.color }} aria-hidden="true" />
          {t.label}
        </button>
      ))}
    </div>
  );
}

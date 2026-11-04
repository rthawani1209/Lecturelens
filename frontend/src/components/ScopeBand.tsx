import type { WatchData } from "@/lib/api";
import { position, timecode } from "@/lib/format";
import styles from "./Watch.module.css";

export const TAG_COLORS: Record<string, string> = {
  whiteboard: "var(--text)",
  diagram: "var(--ch-meaning)",
  professor: "var(--ch-keyword)",
  slide: "var(--ch-ocr)",
  code: "var(--ch-visual)",
  other: "var(--line)",
};

/** Every captured frame as a coloured cell: what was on screen across the lecture. */
export function ScopeBand({
  frames,
  length,
  time,
  onSeek,
}: {
  frames: WatchData["frames"];
  length: number;
  time: number;
  onSeek: (t: number) => void;
}) {
  const present = Object.keys(TAG_COLORS).filter((t) => frames.some((f) => f.tag === t));
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((p) => timecode(p * length));
  return (
    <section className={styles.panel} aria-label="What's on screen">
      <div className={styles.panelHead}>
        <h2 className="label">What&apos;s on screen · {frames.length} frames</h2>
        <ul className={styles.legend}>
          {present.map((t) => (
            <li key={t}>
              <span style={{ background: TAG_COLORS[t] }} aria-hidden="true" />
              {t}
            </li>
          ))}
        </ul>
      </div>
      <div className={styles.band}>
        {frames.map((f, i) => (
          <button
            key={f.t_s}
            type="button"
            tabIndex={i === 0 ? 0 : -1}
            style={{ background: TAG_COLORS[f.tag ?? "other"], opacity: f.t_s <= time ? 1 : 0.45 }}
            onClick={() => onSeek(f.t_s)}
            aria-label={`${f.tag ?? "frame"} at ${timecode(f.t_s)}`}
          />
        ))}
        <span
          className={styles.bandHead}
          style={{ left: position(time, length) }}
          aria-hidden="true"
        />
      </div>
      <div className={`mono ${styles.ticks}`} aria-hidden="true">
        {ticks.map((t, i) => (
          <span key={i}>{t}</span>
        ))}
      </div>
    </section>
  );
}

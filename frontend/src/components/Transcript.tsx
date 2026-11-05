"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { WatchData } from "@/lib/api";
import { highlight, timecode } from "@/lib/format";
import styles from "./Watch.module.css";

type Line = WatchData["transcript"][number];

export function Transcript({
  lines,
  time,
  onSeek,
}: {
  lines: Line[];
  time: number;
  onSeek: (t: number) => void;
}) {
  const [find, setFind] = useState("");
  const [follow, setFollow] = useState(true);
  const list = useRef<HTMLOListElement>(null);

  const active = useMemo(() => {
    let i = -1;
    for (let k = 0; k < lines.length && lines[k].start_s <= time; k++) i = k;
    return i;
  }, [lines, time]);

  const shown = useMemo(() => {
    const q = find.trim().toLowerCase();
    return lines.map((l, i) => ({ ...l, i })).filter((l) => !q || l.text.toLowerCase().includes(q));
  }, [lines, find]);

  // keep the spoken line in view, inside the panel only (never scroll the page)
  useEffect(() => {
    if (!follow || find) return;
    const box = list.current;
    const el = box?.querySelector<HTMLElement>(`[data-line="${active}"]`);
    if (!box || !el) return;
    // measured on screen, so it doesn't matter which element offsetTop counts from
    const y = el.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop;
    box.scrollTop = y - box.clientHeight / 3;
  }, [active, follow, find]);

  return (
    <section className={styles.panel} aria-label="Transcript">
      <div className={styles.panelHead}>
        <h2 className="label">Transcript · follows the video</h2>
        {!follow && (
          <button type="button" className={styles.link} onClick={() => setFollow(true)}>
            Follow video
          </button>
        )}
      </div>
      <label className={styles.find}>
        <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="10.5" cy="10.5" r="6.5" fill="none" stroke="currentColor" strokeWidth="2" />
          <path d="M15.5 15.5 21 21" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
        <span className="sr-only">Find in this lecture</span>
        <input
          type="search"
          placeholder="Find in this lecture"
          value={find}
          onChange={(e) => setFind(e.target.value)}
        />
        {find && <span className="mono">{shown.length}</span>}
      </label>
      <ol className={styles.lines} ref={list} onWheel={() => setFollow(false)}>
        {shown.length === 0 && (
          <li className={styles.none}>
            {lines.length ? "Not said in this lecture." : "No one speaks in this video."}
          </li>
        )}
        {shown.map((l) => (
          <li key={l.i}>
            <button
              type="button"
              data-line={l.i}
              className={l.i === active ? `${styles.line} ${styles.lineOn}` : styles.line}
              aria-current={l.i === active ? "true" : undefined}
              onClick={() => {
                onSeek(l.start_s);
                setFollow(true);
              }}
            >
              <span className="mono">{timecode(l.start_s)}</span>
              <span>
                {find
                  ? highlight(l.text, find).map((p, k) =>
                      p.hit ? <mark key={k}>{p.text}</mark> : <span key={k}>{p.text}</span>,
                    )
                  : l.text}
              </span>
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}

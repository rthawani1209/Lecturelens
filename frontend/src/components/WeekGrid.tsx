import Link from "next/link";
import type { Week } from "@/lib/api";
import { timecode } from "@/lib/format";
import styles from "./WeekGrid.module.css";

const STATUS: Record<string, string> = {
  ready: "",
  failed: "failed",
  queued: "queued",
  processing: "processing",
  uploading: "uploading",
};

export function WeekGrid({ weeks }: { weeks: Week[] }) {
  return (
    <ol className={styles.weeks}>
      {weeks.map((w) => (
        <li key={w.week ?? "none"} className={styles.week}>
          <h3 className="label">{w.week ? `Week ${w.week}` : "Not in a week yet"}</h3>
          <ul>
            {w.lectures.map((l) => (
              <li key={l.id}>
                <Link href={`/watch/${l.id}`} className={styles.lecture}>
                  <span className={`mono ${styles.n}`}>L{l.position}</span>
                  <span className={styles.name}>{l.title.replace(/^Lecture \d+:\s*/, "")}</span>
                  <span className={`mono ${styles.len}`}>
                    {STATUS[l.status] ?? l.status}
                    {l.status === "ready" && l.duration_s ? timecode(l.duration_s) : ""}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ol>
  );
}

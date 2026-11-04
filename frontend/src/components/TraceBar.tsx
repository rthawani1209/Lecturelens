import { position, timecode } from "@/lib/format";
import styles from "./Search.module.css";

/** The whole lecture as a line, with a tick where this moment is. */
export function TraceBar({ at, length }: { at: number; length: number | null }) {
  const pct = position(at, length);
  return (
    <div className={styles.trace}>
      <span className="mono">0:00</span>
      <div className={styles.traceLine} aria-hidden="true">
        <div className={styles.traceDone} style={{ width: pct }} />
        <div className={styles.traceTick} style={{ left: pct }} />
      </div>
      <span className="mono">{length ? timecode(length) : "--:--"}</span>
    </div>
  );
}

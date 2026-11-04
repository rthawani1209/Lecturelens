import type { Hit } from "@/lib/api";
import { position } from "@/lib/format";
import styles from "./Search.module.css";

/** One line per lecture, with a tick for every result in it. */
export function CourseMap({ hits, lectures }: { hits: Hit[]; lectures: number }) {
  const byLecture = new Map<number, Hit[]>();
  for (const h of hits) {
    byLecture.set(h.lecture_position, [...(byLecture.get(h.lecture_position) ?? []), h]);
  }
  const rows = Array.from({ length: lectures }, (_, i) => i + 1);
  return (
    <section className={styles.panel} aria-label="Across the course">
      <h2 className="label">Across the course</h2>
      <p className={styles.panelNote}>Where these moments sit in the {lectures} lectures.</p>
      <ol className={styles.map}>
        {rows.map((n) => {
          const here = byLecture.get(n) ?? [];
          return (
            <li key={n}>
              <span className="mono" style={{ color: here.length ? "var(--accent)" : undefined }}>
                L{n}
              </span>
              <div className={styles.mapLine} aria-hidden="true">
                {here.map((h, i) => (
                  <span key={i} style={{ left: position(h.jump_s, h.lecture_duration_s) }} />
                ))}
              </div>
              {here.length > 0 && (
                <span className="sr-only">
                  {here.length} result{here.length > 1 ? "s" : ""}
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

import { HomeSearch } from "@/components/HomeSearch";
import { WeekGrid } from "@/components/WeekGrid";
import { api, type Course, type Week } from "@/lib/api";
import styles from "./page.module.css";

export const dynamic = "force-dynamic";

const CHANNELS = [
  { label: "Speech", what: "Whisper transcript, every sentence timed", color: "var(--ch-meaning)" },
  { label: "Boards", what: "Handwriting read off the chalkboard", color: "var(--text)" },
  { label: "Slides", what: "Slide and code text, by OCR", color: "var(--ch-ocr)" },
  { label: "Frames", what: "What the picture shows, by CLIP", color: "var(--ch-visual)" },
];

async function load(): Promise<{ courses: Course[]; weeks: Record<string, Week[]> } | null> {
  try {
    const courses = await api.publicCourses();
    const weeks = await Promise.all(courses.map((c) => api.weeks(c.id)));
    return { courses, weeks: Object.fromEntries(courses.map((c, i) => [c.id, weeks[i]])) };
  } catch {
    return null;
  }
}

export default async function Home() {
  const data = await load();
  return (
    <main className={styles.page}>
      <section className={styles.hero}>
        <p className="label">Lecture search · speech, boards, slides and frames</p>
        <h1 className="display">
          Jump to the second
          <br />
          it was <span className={styles.accent}>explained</span>.
        </h1>
        <p className={styles.lede}>
          LectureLens reads every lecture four ways, so you can find a proof, a diagram or a line of
          code by asking for it.
        </p>
        <HomeSearch />
        <ul className={styles.channels} aria-label="What gets indexed">
          {CHANNELS.map((c) => (
            <li key={c.label}>
              <span className={styles.dot} style={{ background: c.color }} aria-hidden="true" />
              <strong>{c.label}</strong>
              <span>{c.what}</span>
            </li>
          ))}
        </ul>
      </section>

      {data === null && (
        <p className={styles.down} role="alert">
          Can&apos;t reach the LectureLens API right now. Courses will show up when it&apos;s back.
        </p>
      )}

      {data?.courses.map((c) => (
        <section key={c.id} className={styles.course} aria-labelledby={`course-${c.id}`}>
          <div className={styles.courseHead}>
            <div>
              <p className="label">
                {c.code} · {c.term || "public"} · {c.lecture_count} lectures
              </p>
              <h2 id={`course-${c.id}`} className="display">
                {c.title}
              </h2>
            </div>
            {c.license && <span className={`mono ${styles.license}`}>{c.license}</span>}
          </div>
          <WeekGrid weeks={data.weeks[c.id]} />
        </section>
      ))}
    </main>
  );
}

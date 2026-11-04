import { WeekGrid } from "@/components/WeekGrid";
import { api } from "@/lib/api";
import styles from "../page.module.css";

export const dynamic = "force-dynamic";

export default async function WatchIndex() {
  const courses = await api.publicCourses().catch(() => null);
  const weeks = courses ? await Promise.all(courses.map((c) => api.weeks(c.id))) : [];
  return (
    <main className={styles.page}>
      <section className={styles.course}>
        <p className="label">Watch</p>
        <h1 className="display" style={{ fontWeight: 500 }}>
          Pick a lecture
        </h1>
      </section>
      {courses === null && (
        <p className={styles.down} role="alert">
          Can&apos;t reach the LectureLens API right now.
        </p>
      )}
      {courses?.map((c, i) => (
        <section key={c.id} className={styles.course} aria-label={c.title}>
          <div className={styles.courseHead}>
            <div>
              <p className="label">
                {c.code} · {c.lecture_count} lectures
              </p>
              <h2 className="display">{c.title}</h2>
            </div>
          </div>
          <WeekGrid weeks={weeks[i]} />
        </section>
      ))}
    </main>
  );
}

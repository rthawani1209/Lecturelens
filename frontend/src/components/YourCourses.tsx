"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type Course, type Week } from "@/lib/api";
import styles from "@/app/page.module.css";
import { WeekGrid } from "./WeekGrid";

/** The signed-in person's own (private) courses. The page around it is rendered on
 * the server, which only knows the public ones. */
export function YourCourses() {
  const [mine, setMine] = useState<{ course: Course; weeks: Week[] }[]>([]);

  useEffect(() => {
    let live = true;
    api
      .me()
      .then((me) => (me ? api.courses() : []))
      .then((all) => all.filter((c) => c.mine && !c.public))
      .then((own) =>
        Promise.all(own.map((c) => api.weeks(c.id).then((weeks) => ({ course: c, weeks })))),
      )
      .then((rows) => live && setMine(rows))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  return mine.map(({ course: c, weeks }) => (
    <section key={c.id} className={styles.course} aria-label={c.title}>
      <div className={styles.courseHead}>
        <div>
          <p className="label">Your course · private · {c.lecture_count} lectures</p>
          <h2 className="display">{c.title}</h2>
        </div>
        <Link href={`/upload?course=${c.id}`} className={`mono ${styles.license}`}>
          Add a lecture
        </Link>
      </div>
      {weeks.length ? <WeekGrid weeks={weeks} /> : <p className={styles.lede}>No lectures yet.</p>}
    </section>
  ));
}

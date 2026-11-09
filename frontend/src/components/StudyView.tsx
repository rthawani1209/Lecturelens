"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  ApiError,
  mediaUrl,
  type Card,
  type Course,
  type Deck,
  type Grade,
  type Me,
  type StudyWeek,
} from "@/lib/api";
import { shortTitle, timecode } from "@/lib/format";
import { AskBox } from "./AskBox";
import styles from "./Study.module.css";

const GRADES: { grade: Grade; label: string; key: string }[] = [
  { grade: "again", label: "Again", key: "1" },
  { grade: "hard", label: "Hard", key: "2" },
  { grade: "good", label: "Good", key: "3" },
  { grade: "easy", label: "Easy", key: "4" },
];

const typing = (el: EventTarget | null) =>
  el instanceof HTMLElement &&
  (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));

export function StudyView() {
  const router = useRouter();
  const params = useSearchParams();
  const courseParam = params.get("course");
  const lectureParam = params.get("lecture");

  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [courses, setCourses] = useState<Course[]>([]);
  const [weeks, setWeeks] = useState<StudyWeek[] | null>(null);
  const [deck, setDeck] = useState<Deck | null>(null);
  const [queue, setQueue] = useState<Card[]>([]);
  const [done, setDone] = useState(0);
  const [shown, setShown] = useState(false);
  const [loadingDeck, setLoadingDeck] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // a link to one lecture ("Study this lecture") opens that lecture's course
  const courseId = courseParam ?? deck?.course_id ?? (lectureParam ? null : courses[0]?.id) ?? null;
  const course = courses.find((c) => c.id === courseId);

  const main = useRef<HTMLElement>(null);
  const go = useCallback(
    (next: { course?: string; lecture?: string | null }) => {
      const p = new URLSearchParams(params.toString());
      if (next.course) p.set("course", next.course);
      if (next.lecture === null) p.delete("lecture");
      else if (next.lecture) p.set("lecture", next.lecture);
      router.replace(`/study?${p}`, { scroll: false });
      // on a phone the deck list sits above the card, so bring the card up
      if (next.lecture && window.matchMedia("(max-width: 959px)").matches) {
        main.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    },
    [params, router],
  );

  useEffect(() => {
    api.me().then(setMe, () => setMe(null));
  }, []);

  useEffect(() => {
    if (!me) return;
    api.courses().then(
      (all) => setCourses(all.filter((c) => c.lecture_count > 0)),
      (e: Error) => setError(e.message),
    );
  }, [me]);

  const refreshWeeks = useCallback(() => {
    if (!courseId) return;
    api.studyCourse(courseId).then(setWeeks, (e: Error) => setError(e.message));
  }, [courseId]);

  useEffect(() => {
    setWeeks(null);
    refreshWeeks();
  }, [refreshWeeks]);

  useEffect(() => {
    if (!lectureParam || !me) {
      setDeck(null);
      return;
    }
    let live = true;
    setLoadingDeck(true);
    setError(null);
    setShown(false);
    setDone(0);
    api
      .openDeck(lectureParam)
      .then((d) => {
        if (!live) return;
        setDeck(d);
        setQueue(d.cards.filter((c) => new Date(c.due_at) <= new Date()));
        refreshWeeks();
      })
      .catch((e: unknown) => {
        if (!live) return;
        setDeck(null);
        // a link to a lecture that doesn't exist (or a mangled id) gets plain words
        const missing = e instanceof ApiError && (e.status === 404 || e.status === 422);
        setError(
          missing
            ? "That lecture doesn't exist, or isn't shared with you. Pick one from the list."
            : e instanceof Error
              ? e.message
              : "Couldn't open the deck.",
        );
      })
      .finally(() => live && setLoadingDeck(false));
    return () => {
      live = false;
    };
  }, [lectureParam, me, refreshWeeks]);

  const card = queue[0];

  const grade = useCallback(
    async (g: Grade) => {
      if (!card) return;
      const updated = await api.review(card.id, g).catch((e: Error) => {
        setError(e.message);
        return null;
      });
      if (!updated) return;
      setShown(false);
      setDone((n) => n + 1);
      refreshWeeks();
      // "again" comes back at the end of this session; the rest are done for today
      setQueue((q) =>
        g === "again"
          ? [...q.slice(1), { ...card, ...updated, thumb_url: card.thumb_url }]
          : q.slice(1),
      );
    },
    [card, refreshWeeks],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (typing(e.target) || e.metaKey || e.ctrlKey || e.altKey || !card) return;
      if (e.key === " " && !shown) {
        e.preventDefault();
        setShown(true);
      } else if (shown) {
        const g = GRADES.find((x) => x.key === e.key);
        if (g) {
          e.preventDefault();
          grade(g.grade);
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [card, shown, grade]);

  const total = done + queue.length;
  const pips = useMemo(
    () =>
      Array.from({ length: Math.min(total, 24) }, (_, i) =>
        i < done ? "done" : i === done ? "now" : "todo",
      ),
    [done, total],
  );

  if (me === undefined) return <main className={styles.page} aria-busy="true" />;

  if (me === null) {
    return (
      <main className={styles.page}>
        <section className={styles.gate}>
          <p className="label">Study</p>
          <h1 className="display">Flashcards from every lecture</h1>
          <p>
            Cards are written from the lecture itself and link back to the second each idea was
            taught. Sign in so we can remember what you&apos;ve learned.
          </p>
          <Link
            className={styles.primary}
            href={`/signin?next=${encodeURIComponent(`/study?${params}`)}`}
          >
            Sign in
          </Link>
        </section>
      </main>
    );
  }

  const lectures = weeks?.flatMap((w) => w.lectures) ?? [];
  const current = lectures.find((l) => l.id === lectureParam);

  return (
    <main className={styles.page}>
      <aside className={styles.side} aria-label="Decks">
        {courses.length > 1 && (
          <select
            aria-label="Course"
            className={styles.coursePick}
            value={courseId ?? ""}
            onChange={(e) => go({ course: e.target.value, lecture: null })}
          >
            {courses.map((c) => (
              <option key={c.id} value={c.id}>
                {c.code ? `${c.code} · ${c.title}` : c.title}
              </option>
            ))}
          </select>
        )}
        {weeks === null && <div className={styles.sideSkeleton} aria-busy="true" />}
        {weeks?.length === 0 && (
          <p className={styles.hint}>No finished lectures in this course yet.</p>
        )}
        {weeks?.map((w) => (
          <div key={w.week ?? "none"} className={styles.weekGroup}>
            <p className="label">
              {course?.code ? `${course.code} · ` : ""}
              {w.week === null ? "More lectures" : `Week ${w.week}`}
            </p>
            {w.lectures.map((l) => (
              <button
                key={l.id}
                type="button"
                className={`${styles.deck} ${l.id === lectureParam ? styles.on : ""}`}
                aria-current={l.id === lectureParam ? "true" : undefined}
                onClick={() => go({ lecture: l.id })}
              >
                <span>{shortTitle(l.title, l.position)}</span>
                <span className={`mono ${l.due ? styles.dueCount : ""}`}>
                  {!l.started ? "new" : l.due ? `${l.due} due` : "done"}
                </span>
              </button>
            ))}
          </div>
        ))}
        <div className={styles.note}>
          Every card is written from the lecture itself and links back to the second it came from.
        </div>
      </aside>

      <section className={styles.main} aria-label="Card" ref={main}>
        {error && (
          <p className={styles.error} role="alert">
            {error}
          </p>
        )}

        {!lectureParam && (
          <div className={styles.empty}>
            <p className="label">Pick a lecture</p>
            <h1 className="display">Choose a deck on the left</h1>
            <p>
              The first time you open a lecture we write its cards. After that, cards come back on a
              spaced schedule: the better you know one, the longer until you see it again.
            </p>
          </div>
        )}

        {lectureParam && loadingDeck && (
          <div className={`${styles.card} ${styles.writing}`} aria-busy="true">
            <p className="label">Writing cards</p>
            <p>Reading the lecture and picking what&apos;s worth remembering…</p>
          </div>
        )}

        {deck && !loadingDeck && (
          <>
            <div className={styles.progress}>
              <div className={styles.pips} aria-hidden="true">
                {pips.map((p, i) => (
                  <span key={i} className={styles[`pip_${p}`]} />
                ))}
              </div>
              <span className="mono">
                {card ? `card ${done + 1} of ${total}` : `${deck.total} cards`} · {deck.course_code}
              </span>
            </div>

            {card ? (
              <div className={styles.card}>
                <span className={`${styles.ret} ${styles.retTl}`} aria-hidden="true" />
                <span className={`${styles.ret} ${styles.retBr}`} aria-hidden="true" />
                <p className={`label ${styles.qLabel}`}>Question</p>
                <h1 className={`display ${card.front.length > 140 ? styles.long : ""}`}>
                  {card.front}
                </h1>
                {shown ? (
                  <div className={styles.back}>
                    <p className={`label ${styles.aLabel}`}>Answer</p>
                    <p className={styles.answerBig}>{card.back}</p>
                    {card.t_s !== null && (
                      <Link
                        className={styles.taught}
                        href={`/watch/${deck.lecture_id}?t=${Math.floor(card.t_s)}`}
                      >
                        {card.thumb_url && (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img src={mediaUrl(card.thumb_url) ?? ""} alt="" />
                        )}
                        <span>
                          <span className="mono">
                            ▶ {timecode(card.t_s)} ·{" "}
                            {shortTitle(deck.lecture_title, current?.position ?? 0).split(" · ")[0]}
                          </span>
                          <span>Watch where this was taught</span>
                        </span>
                      </Link>
                    )}
                  </div>
                ) : (
                  <button type="button" className={styles.reveal} onClick={() => setShown(true)}>
                    Show answer <span className="mono">space</span>
                  </button>
                )}
              </div>
            ) : (
              <div className={`${styles.card} ${styles.finished}`}>
                <span className={`${styles.ret} ${styles.retTl}`} aria-hidden="true" />
                <span className={`${styles.ret} ${styles.retBr}`} aria-hidden="true" />
                <p className={`label ${styles.aLabel}`}>All caught up</p>
                <h1 className="display">
                  {done
                    ? `${done} card${done === 1 ? "" : "s"} reviewed.`
                    : "Nothing due in this deck."}
                </h1>
                <p>{nextDue(deck, done)}</p>
                <div className={styles.finishedRow}>
                  <Link className={styles.primary} href={`/watch/${deck.lecture_id}`}>
                    Watch the lecture
                  </Link>
                  {lectures.some((l) => l.due > 0 && l.id !== deck.lecture_id) && (
                    <button
                      type="button"
                      className={styles.secondary}
                      onClick={() =>
                        go({
                          lecture: lectures.find((l) => l.due > 0 && l.id !== deck.lecture_id)!.id,
                        })
                      }
                    >
                      Next deck with cards due
                    </button>
                  )}
                </div>
              </div>
            )}

            {card && shown && (
              <div role="group" aria-label="How well did you know it?" className={styles.rates}>
                {GRADES.map((g) => (
                  <button
                    key={g.grade}
                    type="button"
                    className={styles.rate}
                    onClick={() => grade(g.grade)}
                  >
                    <span>{g.label}</span>
                    <span className="mono">
                      {card.preview[g.grade]} · {g.key}
                    </span>
                  </button>
                ))}
              </div>
            )}

            {courseId && (
              <AskBox key={deck.lecture_id} lectureId={deck.lecture_id} courseId={courseId} />
            )}
          </>
        )}
      </section>
    </main>
  );
}

function nextDue(deck: Deck, reviewed: number): string {
  if (reviewed) return "Come back tomorrow; cards you knew well will wait longer.";
  const soonest = deck.cards
    .map((c) => new Date(c.due_at).getTime())
    .filter((t) => t > Date.now())
    .sort((a, b) => a - b)[0];
  if (!soonest) return "";
  const days = Math.max(1, Math.round((soonest - Date.now()) / 86_400_000));
  return `The next card is due in ${days} day${days === 1 ? "" : "s"}.`;
}

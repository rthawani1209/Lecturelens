"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type Course, type Me } from "@/lib/api";
import { upload, UploadError, type Progress } from "@/lib/upload";
import { MyLectures } from "./MyLectures";
import { Pipeline } from "./Pipeline";
import styles from "./Upload.module.css";

const ACCEPT = ".mp4,.mov,.m4v,.mkv,.webm";
const SAVED = "ll-uploads";

type Sending = {
  file: File;
  lectureId: string;
  url: string;
  chunk: number;
  progress: Progress;
  state: "sending" | "paused" | "error";
  error?: string;
};

// Unfinished uploads are remembered per file, so picking the same file again after
// a reload carries on where it stopped instead of starting a second lecture.
type Saved = Record<string, { lectureId: string; url: string; chunk: number }>;

const fileKey = (course: string, f: File) => `${course}:${f.name}:${f.size}:${f.lastModified}`;

function loadSaved(): Saved {
  try {
    return JSON.parse(localStorage.getItem(SAVED) ?? "{}") as Saved;
  } catch {
    return {};
  }
}

function save(update: (s: Saved) => void) {
  try {
    const s = loadSaved();
    update(s);
    localStorage.setItem(SAVED, JSON.stringify(s));
  } catch {
    // private mode; resume just won't survive a reload
  }
}

function forget(lectureId: string) {
  save((saved) => {
    for (const [k, v] of Object.entries(saved)) if (v.lectureId === lectureId) delete saved[k];
  });
}

const mb = (n: number) => `${(n / 1024 ** 2).toFixed(n < 10 * 1024 ** 2 ? 1 : 0)} MB`;

function message(e: unknown): string {
  if (e instanceof ApiError || e instanceof Error) return e.message;
  return "Something went wrong.";
}

export function UploadView() {
  const router = useRouter();
  const params = useSearchParams();
  const lectureParam = params.get("lecture");

  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [courses, setCourses] = useState<Course[]>([]);
  const [courseId, setCourseId] = useState("");
  const [newCourse, setNewCourse] = useState(false);
  const [courseTitle, setCourseTitle] = useState("");
  const [courseCode, setCourseCode] = useState("");
  const [title, setTitle] = useState("");
  const [week, setWeek] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [youtube, setYoutube] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sending, setSending] = useState<Sending | null>(null);
  const [limit, setLimit] = useState("4 GB");
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    api.me().then(setMe, () => setMe(null));
    api.providers().then(
      (p) => p.max_upload_bytes && setLimit(sizeLabel(p.max_upload_bytes)),
      () => {},
    );
  }, []);

  useEffect(() => {
    if (!me) return;
    api.courses().then(
      (all) => {
        const mine = all.filter((c) => c.mine);
        setCourses(mine);
        setCourseId((cur) => cur || mine[0]?.id || "");
        if (mine.length === 0) setNewCourse(true);
      },
      (e) => setFormError(message(e)),
    );
  }, [me]);

  // stop sending if the user navigates away; the server keeps what it got
  useEffect(() => () => abort.current?.abort(), []);

  const showLecture = useCallback(
    (id: string | null) =>
      router.replace(id ? `/upload?lecture=${id}` : "/upload", { scroll: false }),
    [router],
  );

  const pick = (f: File | undefined) => {
    if (!f) return;
    setFormError(null);
    setFile(f);
    // a title we made from the last file follows the new one; a typed one stays
    const fromName = (n: string) => n.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ");
    if (!title || (file && title === fromName(file.name))) setTitle(fromName(f.name));
  };

  async function ensureCourse(): Promise<string> {
    if (!newCourse) {
      if (!courseId) throw new Error("Pick a course first.");
      return courseId;
    }
    if (!courseTitle.trim()) throw new Error("Give the new course a name.");
    const c = await api.createCourse(courseTitle.trim(), courseCode.trim());
    setCourses((cs) => [...cs, c]);
    setCourseId(c.id);
    setNewCourse(false);
    return c.id;
  }

  const weekNumber = () => (week.trim() === "" ? null : Number(week));

  async function send(s: Sending) {
    const ctl = new AbortController();
    abort.current = ctl;
    setSending({ ...s, state: "sending", error: undefined });
    try {
      const done = await upload(`/api${s.url}`, s.file, {
        chunk: s.chunk,
        signal: ctl.signal,
        onProgress: (progress) => setSending((cur) => (cur ? { ...cur, progress } : cur)),
      });
      forget(s.lectureId);
      setSending(null);
      setFile(null);
      setTitle("");
      // the course may already have had this video; then we show that lecture
      showLecture(done.lecture_id ?? s.lectureId);
    } catch (e) {
      if (e instanceof UploadError && e.refused) {
        // the server dropped this lecture; start clean next time
        forget(s.lectureId);
        setSending(null);
        setFile(null);
        setTitle("");
        setFormError(e.message);
        return;
      }
      const aborted = ctl.signal.aborted;
      setSending((cur) =>
        cur
          ? { ...cur, state: aborted ? "paused" : "error", error: aborted ? undefined : message(e) }
          : cur,
      );
    }
  }

  async function startUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!file) {
      setFormError("Choose a video file first.");
      return;
    }
    setBusy(true);
    setFormError(null);
    try {
      const cid = await ensureCourse();
      const key = fileKey(cid, file);
      const prior = loadSaved()[key];
      let job = prior;
      if (!job) {
        const r = await api.startUpload(cid, {
          title: title.trim() || file.name,
          filename: file.name,
          size: file.size,
          week: weekNumber(),
        });
        job = { lectureId: r.lecture_id, url: r.upload_url, chunk: r.chunk_size };
        save((saved) => {
          saved[key] = job!;
        });
      }
      await send({
        file,
        ...job,
        progress: { sent: 0, total: file.size },
        state: "sending",
      });
    } catch (err) {
      setFormError(message(err));
    } finally {
      setBusy(false);
    }
  }

  async function importVideo(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setFormError(null);
    try {
      const cid = await ensureCourse();
      const lec = await api.importYoutube(cid, {
        url: youtube.trim(),
        title: title.trim(),
        week: weekNumber(),
      });
      setYoutube("");
      showLecture(lec.id);
    } catch (err) {
      setFormError(message(err));
    } finally {
      setBusy(false);
    }
  }

  if (me === undefined) return <main className={styles.page} aria-busy="true" />;

  if (me === null) {
    return (
      <main className={styles.page}>
        <p className={`mono label ${styles.kicker}`}>Add to a course</p>
        <h1 className={`display ${styles.title}`}>Add a lecture</h1>
        <div className={styles.gate}>
          <p>
            Sign in to upload lectures to your own courses. Public courses stay searchable without
            an account.
          </p>
          <Link className={styles.primary} href="/signin?next=/upload">
            Sign in
          </Link>
        </div>
      </main>
    );
  }

  const course = courses.find((c) => c.id === courseId);
  const pct = sending
    ? Math.round((sending.progress.sent / Math.max(1, sending.progress.total)) * 100)
    : 0;

  return (
    <main className={styles.page}>
      <p className={`mono label ${styles.kicker}`}>
        {course ? `Add to ${course.code || course.title}` : "Add to a course"} · private to your
        group until you publish
      </p>
      <h1 className={`display ${styles.title}`}>Add a lecture</h1>

      <div className={styles.details}>
        <div className={styles.field}>
          <label htmlFor="course">Course</label>
          {newCourse ? (
            <div className={styles.newCourse}>
              <input
                id="course"
                placeholder="Course name, e.g. Linear Algebra"
                value={courseTitle}
                onChange={(e) => setCourseTitle(e.target.value)}
              />
              <input
                aria-label="Course code"
                placeholder="Code, e.g. 18.06"
                value={courseCode}
                onChange={(e) => setCourseCode(e.target.value)}
              />
              {courses.length > 0 && (
                <button type="button" className={styles.link} onClick={() => setNewCourse(false)}>
                  Use an existing course
                </button>
              )}
            </div>
          ) : (
            <div className={styles.newCourse}>
              <select id="course" value={courseId} onChange={(e) => setCourseId(e.target.value)}>
                {courses.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.code ? `${c.code} · ${c.title}` : c.title}
                  </option>
                ))}
              </select>
              <button type="button" className={styles.link} onClick={() => setNewCourse(true)}>
                New course
              </button>
            </div>
          )}
        </div>
        <div className={styles.field}>
          <label htmlFor="title">Lecture title</label>
          <input
            id="title"
            placeholder="Lecture 13: Dijkstra"
            maxLength={200}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>
        <div className={`${styles.field} ${styles.narrow}`}>
          <label htmlFor="week">Week</label>
          <input
            id="week"
            type="number"
            inputMode="numeric"
            min={0}
            max={52}
            placeholder="—"
            value={week}
            onChange={(e) => setWeek(e.target.value)}
          />
        </div>
      </div>

      {formError && (
        <p className={styles.error} role="alert">
          {formError}
        </p>
      )}

      <div className={styles.row}>
        <form className={styles.dropForm} onSubmit={startUpload}>
          <label
            htmlFor="file"
            className={`${styles.drop} ${dragging ? styles.dragging : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              pick(e.dataTransfer.files[0]);
            }}
          >
            <svg width="56" height="56" viewBox="0 0 56 56" aria-hidden="true">
              <circle cx="28" cy="28" r="26" fill="none" stroke="var(--line)" strokeWidth="1.5" />
              <circle
                cx="28"
                cy="28"
                r="17"
                fill="none"
                stroke="var(--accent)"
                strokeWidth="1.5"
                strokeDasharray="4 5"
                className={sending?.state === "sending" ? styles.spin : undefined}
              />
              <path
                d="M28 36V20M21 27l7-7 7 7"
                fill="none"
                stroke="var(--text)"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            {file ? (
              <>
                <span className={styles.dropTitle}>{file.name}</span>
                <span className="mono">{mb(file.size)} · click to choose a different file</span>
              </>
            ) : (
              <>
                <span className={styles.dropTitle}>Drop a lecture video, or browse</span>
                <span className="mono">
                  mp4 · mov · m4v · mkv · webm, up to {limit}. Uploads resume if the connection
                  drops.
                </span>
              </>
            )}
            <input
              id="file"
              type="file"
              accept={ACCEPT}
              className="sr-only"
              disabled={!!sending}
              onChange={(e) => pick(e.target.files?.[0])}
            />
          </label>

          {sending ? (
            <div className={styles.sending} aria-live="polite">
              <div className={styles.sendHead}>
                <span className="mono">
                  {sending.state === "sending"
                    ? `Uploading ${pct}%`
                    : sending.state === "paused"
                      ? `Paused at ${pct}%`
                      : `Stopped at ${pct}%`}
                </span>
                <span className="mono">
                  {mb(sending.progress.sent)} of {mb(sending.progress.total)}
                </span>
              </div>
              <div
                className={styles.track}
                role="progressbar"
                aria-label="Upload progress"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={pct}
              >
                <span style={{ width: `${pct}%` }} />
              </div>
              {sending.error && <p className={styles.error}>{sending.error}</p>}
              <div className={styles.actions}>
                {sending.state === "sending" ? (
                  <button
                    type="button"
                    className={styles.secondary}
                    onClick={() => abort.current?.abort()}
                  >
                    Cancel
                  </button>
                ) : (
                  <>
                    <button type="button" className={styles.primary} onClick={() => send(sending)}>
                      {sending.state === "paused" ? "Resume" : "Retry"}
                    </button>
                    <button
                      type="button"
                      className={styles.secondary}
                      onClick={async () => {
                        const id = sending.lectureId;
                        forget(id);
                        setSending(null);
                        await api.deleteLecture(id).catch(() => undefined);
                      }}
                    >
                      Discard
                    </button>
                  </>
                )}
              </div>
            </div>
          ) : (
            <button type="submit" className={styles.primary} disabled={busy || !file}>
              {busy ? "Starting…" : "Upload"}
            </button>
          )}
        </form>

        <form className={styles.yt} onSubmit={importVideo}>
          <label htmlFor="yt">Import from YouTube</label>
          <span>
            Paste a link to a lecture you&apos;re allowed to use. Audio is transcribed again so
            search can jump to the second.
          </span>
          <input
            id="yt"
            type="url"
            required
            placeholder="https://www.youtube.com/watch?v=…"
            value={youtube}
            onChange={(e) => setYoutube(e.target.value)}
          />
          <button type="submit" className={styles.primary} disabled={busy || !youtube.trim()}>
            Import
          </button>
        </form>
      </div>

      {lectureParam && (
        <Pipeline key={lectureParam} id={lectureParam} onDeleted={() => showLecture(null)} />
      )}

      {courseId && !newCourse && (
        <MyLectures courseId={courseId} current={lectureParam} onOpen={showLecture} />
      )}
    </main>
  );
}

// same wording as the server's "too big" message
function sizeLabel(bytes: number): string {
  const gb = bytes / 1024 ** 3;
  return gb >= 1 ? `${+gb.toFixed(2)} GB` : `${+(bytes / 1024 ** 2).toFixed(2)} MB`;
}

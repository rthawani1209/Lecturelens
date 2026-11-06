// Typed calls to the FastAPI backend. The browser goes through /api (see
// next.config.ts); server components call API_URL directly.

export type Mode = "meaning" | "hybrid" | "keyword" | "text" | "visual";
export type Tag = "slide" | "code" | "whiteboard" | "diagram" | "professor";

export type Course = {
  id: string;
  code: string;
  title: string;
  term: string;
  license: string;
  public: boolean;
  mine: boolean;
  lecture_count: number;
};

export type Lecture = {
  id: string;
  title: string;
  week: number | null;
  position: number;
  duration_s: number | null;
  status: string;
};

export type Week = { week: number | null; lectures: Lecture[] };

export type Hit = {
  lecture_id: string;
  lecture_title: string;
  week: number | null;
  lecture_position: number;
  lecture_duration_s: number | null;
  start_s: number;
  end_s: number;
  jump_s: number;
  sentence: string;
  text: string;
  frame_t: number | null;
  thumb_url: string | null;
  tag: string | null;
  ocr_text: string;
  score: number;
  matched_by: string[];
};

export type Me = { id: string; email: string; name: string | null };

export type WatchData = {
  id: string;
  title: string;
  week: number | null;
  position: number;
  duration_s: number | null;
  status: string;
  course: { id: string; code: string; title: string };
  video_url: string | null;
  transcript: { start_s: number; end_s: number; text: string }[];
  frames: { t_s: number; tag: string | null; thumb_url: string | null }[];
};

export type Stage = { stage: string; status: string; progress: number; error: string | null };

export type LectureDetail = {
  id: string;
  course_id: string;
  title: string;
  week: number | null;
  duration_s: number | null;
  status: string;
  source_url: string | null;
  progress: number;
  stages: Stage[];
};

export type Note = { id: string; t_s: number; text: string };

export type DeckLecture = {
  id: string;
  title: string;
  week: number | null;
  position: number;
  cards: number;
  due: number;
  started: boolean;
};

export type StudyWeek = { week: number | null; lectures: DeckLecture[] };

export type Grade = "again" | "hard" | "good" | "easy";

export type Card = {
  id: string;
  front: string;
  back: string;
  t_s: number | null;
  thumb_url: string | null;
  due_at: string;
  reps: number;
  preview: Record<Grade, string>;
};

export type Deck = {
  lecture_id: string;
  course_id: string;
  lecture_title: string;
  course_code: string;
  mode: "claude" | "cloze";
  total: number;
  due: number;
  cards: Card[];
};

export type Answer = {
  covered: boolean;
  mode: "claude" | "extractive";
  sentences: { text: string; cites: number[] }[];
  sources: { n: number; start_s: number; text: string }[];
};

export type SearchResult = { query: string; mode: Mode; hits: Hit[] };

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

function base(): string {
  return typeof window === "undefined" ? (process.env.API_URL ?? "http://localhost:8000") : "/api";
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(base() + path, { credentials: "include", ...init });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = typeof body.detail === "string" ? body.detail : res.statusText;
    throw new ApiError(res.status, detail);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

const get = call;

function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  return call<T>(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export const api = {
  publicCourses: () => get<Course[]>("/courses/public", { cache: "no-store" }),
  weeks: (courseId: string) => get<Week[]>(`/courses/${courseId}/weeks`, { cache: "no-store" }),
  search: (
    q: string,
    opts: { course?: string; mode?: Mode; tag?: Tag; limit?: number; signal?: AbortSignal } = {},
  ) => {
    const p = new URLSearchParams({ q, limit: String(opts.limit ?? 10) });
    if (opts.course) p.set("course", opts.course);
    if (opts.mode) p.set("mode", opts.mode);
    if (opts.tag) p.set("tag", opts.tag);
    return get<SearchResult>(`/search?${p}`, { signal: opts.signal });
  },
  providers: () =>
    get<{ email: boolean; google: boolean; demo?: boolean; max_upload_bytes?: number }>(
      "/auth/providers",
    ),
  me: () => get<{ user: Me | null }>("/auth/session", { cache: "no-store" }).then((s) => s.user),
  emailLink: (email: string) => send<void>("POST", "/auth/email", { email }),
  verify: (token: string) => send<Me>("POST", "/auth/email/verify", { token }),
  demo: () => send<Me>("POST", "/auth/demo"),
  logout: () => send<void>("POST", "/auth/logout"),
  watch: (id: string) => get<WatchData>(`/lectures/${id}/watch`, { cache: "no-store" }),
  notes: (id: string) => get<Note[]>(`/lectures/${id}/notes`, { cache: "no-store" }),
  addNote: (id: string, t_s: number, text: string) =>
    send<Note>("POST", `/lectures/${id}/notes`, { t_s, text }),
  deleteNote: (noteId: string) => send<void>("DELETE", `/notes/${noteId}`),
  editNote: (noteId: string, text: string) => send<Note>("PATCH", `/notes/${noteId}`, { text }),
  courses: () => get<Course[]>("/courses", { cache: "no-store" }),
  createCourse: (title: string, code: string) => send<Course>("POST", "/courses", { title, code }),
  startUpload: (
    courseId: string,
    body: { title: string; filename: string; size: number; week: number | null },
  ) =>
    send<{ lecture_id: string; upload_url: string; chunk_size: number }>(
      "POST",
      `/courses/${courseId}/lectures`,
      body,
    ),
  importYoutube: (courseId: string, body: { url: string; title: string; week: number | null }) =>
    send<LectureDetail>("POST", `/courses/${courseId}/lectures/import`, body),
  lecture: (id: string) => get<LectureDetail>(`/lectures/${id}`, { cache: "no-store" }),
  lectures: (courseId: string) =>
    get<Lecture[]>(`/courses/${courseId}/lectures`, { cache: "no-store" }),
  retry: (id: string) => send<LectureDetail>("POST", `/lectures/${id}/retry`),
  deleteLecture: (id: string) => send<void>("DELETE", `/lectures/${id}`),
  studyCourse: (courseId: string) =>
    get<StudyWeek[]>(`/study/courses/${courseId}`, { cache: "no-store" }),
  openDeck: (lectureId: string) => send<Deck>("POST", `/lectures/${lectureId}/deck`),
  review: (cardId: string, grade: Grade) =>
    send<Card>("POST", `/cards/${cardId}/review`, { grade }),
  ask: (lectureId: string, question: string) =>
    send<Answer>("POST", `/lectures/${lectureId}/ask`, { question }),
};

/** Media paths from the API are relative to it; send them through the proxy. */
export function mediaUrl(path: string | null): string | null {
  return path ? `/api${path}` : null;
}

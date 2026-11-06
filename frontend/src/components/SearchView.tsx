"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type Course, type Hit, type Mode, type Tag } from "@/lib/api";
import { CourseMap } from "./CourseMap";
import { FilterChips, TAGS } from "./FilterChips";
import { ResultCard, watchHref } from "./ResultCard";
import { MODES, SearchBox } from "./SearchBox";
import styles from "./SearchView.module.css";

const EXAMPLES = [
  "why can't dijkstra handle negative edge weights",
  "how does a hash table resolve collisions",
  "proof that comparison sorting needs n log n",
];

type State =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "done"; hits: Hit[]; mode: Mode };

function isMode(m: string | null): m is Mode {
  return MODES.some((x) => x.id === m);
}

function isTag(t: string | null): t is Tag {
  return TAGS.some((x) => x.id === t && x.id !== "all");
}

export function SearchView({ courses: shared }: { courses: Course[] }) {
  const router = useRouter();
  const params = useSearchParams();
  const q = (params.get("q") ?? "").slice(0, 300); // the API takes at most 300
  const mode: Mode = isMode(params.get("mode")) ? (params.get("mode") as Mode) : "meaning";
  const tag: Tag | "all" = isTag(params.get("tag")) ? (params.get("tag") as Tag) : "all";
  // no course in the URL means every course this person can see
  const courseId = params.get("course") ?? "";
  // the server only sends public courses; add the signed-in person's own
  const [own, setOwn] = useState<Course[]>([]);
  useEffect(() => {
    api
      .me()
      .then((me) => (me ? api.courses() : []))
      .then((all) => setOwn(all.filter((c) => c.mine && !c.public)))
      .catch(() => undefined);
  }, []);
  const courses = useMemo(() => [...own, ...shared], [own, shared]);
  const course = courses.find((c) => c.id === courseId);

  const [state, setState] = useState<State>({ kind: "idle" });
  const [selected, setSelected] = useState(0);
  const [attempt, setAttempt] = useState(0);

  const go = useCallback(
    (next: { q?: string; mode?: Mode; tag?: Tag | "all"; course?: string }) => {
      const p = new URLSearchParams(params.toString());
      for (const [k, v] of Object.entries(next)) {
        if (v === undefined) continue;
        if (!v || (k === "tag" && v === "all") || (k === "mode" && v === "meaning")) p.delete(k);
        else p.set(k, v);
      }
      // a new question is a new page, so Back returns to the last one; filters aren't
      const url = `/search?${p}`;
      if (next.q !== undefined || next.course !== undefined) router.push(url, { scroll: false });
      else router.replace(url, { scroll: false });
    },
    [params, router],
  );

  useEffect(() => {
    if (!q) {
      setState({ kind: "idle" });
      return;
    }
    const ctrl = new AbortController();
    setState({ kind: "loading" });
    api
      .search(q, {
        course: courseId || undefined,
        mode,
        tag: tag === "all" ? undefined : tag,
        signal: ctrl.signal,
      })
      .then((r) => {
        setState({ kind: "done", hits: r.hits, mode: r.mode });
        setSelected(0);
      })
      .catch((e: Error) => {
        if (e.name !== "AbortError") setState({ kind: "error", message: e.message });
      });
    return () => ctrl.abort();
  }, [q, mode, tag, courseId, attempt]);

  // arrows move through results, enter opens one, 1-6 pick a filter
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const el = e.target as HTMLElement;
      if (["INPUT", "TEXTAREA"].includes(el.tagName) || e.metaKey || e.ctrlKey || e.altKey) return;
      const hits = state.kind === "done" ? state.hits : [];
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        if (!hits.length) return;
        e.preventDefault();
        const next = (selected + (e.key === "ArrowDown" ? 1 : -1) + hits.length) % hits.length;
        setSelected(next);
        document.querySelector(`[data-result="${next}"]`)?.scrollIntoView({ block: "nearest" });
      } else if (e.key === "Enter" && hits[selected]) {
        router.push(watchHref(hits[selected]));
      } else if (/^[1-6]$/.test(e.key)) {
        go({ tag: TAGS[Number(e.key) - 1].id });
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [state, selected, go, router]);

  const hits = state.kind === "done" ? state.hits : [];
  const lectures = new Set(hits.map((h) => h.lecture_id)).size;
  const tagLabel = TAGS.find((t) => t.id === tag)?.label.toLowerCase();

  return (
    <main className={styles.page}>
      <div className={styles.top}>
        <p className="label">
          {course
            ? `Search ${course.code || course.title} · ${course.lecture_count} lectures · speech, boards, slides and frames`
            : "Search every lecture you can see"}
        </p>
        {courses.length > 1 && (
          <label className={styles.course}>
            <span className="sr-only">Course</span>
            <select value={courseId} onChange={(e) => go({ course: e.target.value })}>
              <option value="">All courses</option>
              {courses.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.code ? `${c.code} · ${c.title}` : c.title}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      <SearchBox
        initial={q}
        mode={mode}
        onModeChange={(m) => go({ mode: m })}
        onSubmit={(next) => go({ q: next })}
        autoFocus={!q}
      />

      <div className={styles.filters}>
        <FilterChips value={tag} onChange={(t) => go({ tag: t })} />
      </div>

      <div className={styles.columns}>
        <section
          className={styles.results}
          aria-label="Results"
          aria-busy={state.kind === "loading"}
        >
          {state.kind === "idle" && (
            <div className={styles.idle}>
              <h1 className="display">Find the moment it was explained.</h1>
              <p>Try one of these:</p>
              <ul>
                {EXAMPLES.map((ex) => (
                  <li key={ex}>
                    <button type="button" onClick={() => go({ q: ex })}>
                      {ex}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {state.kind === "loading" && (
            <>
              <h1 className={`display ${styles.count}`}>Searching…</h1>
              {[0, 1, 2].map((i) => (
                <div key={i} className={styles.skeleton} aria-hidden="true" />
              ))}
            </>
          )}

          {state.kind === "error" && (
            <div className={styles.error} role="alert">
              <p>Search failed: {state.message}</p>
              <button type="button" onClick={() => setAttempt((n) => n + 1)}>
                Try again
              </button>
            </div>
          )}

          {state.kind === "done" && (
            <>
              <div className={styles.countRow}>
                <h1 className={`display ${styles.count}`} aria-live="polite">
                  {hits.length} moment{hits.length === 1 ? "" : "s"} in {lectures} lecture
                  {lectures === 1 ? "" : "s"}
                </h1>
                <span className="mono">best moment first · jumps to the second</span>
              </div>
              {hits.length === 0 && (
                <div className={styles.empty}>
                  {tag === "all"
                    ? "Nothing in these lectures matches that. Try other words, or switch to Hybrid."
                    : `No ${tagLabel} frames near these moments. Try another filter.`}
                </div>
              )}
              {hits.map((h, i) => (
                <ResultCard
                  key={`${h.lecture_id}-${h.start_s}`}
                  hit={h}
                  query={q}
                  selected={i === selected}
                  index={i}
                />
              ))}
            </>
          )}
        </section>

        <aside className={styles.side}>
          {course && <CourseMap hits={hits} lectures={course.lecture_count} />}
          <section className={styles.keys} aria-label="Keyboard shortcuts">
            <h2 className="label">Keys</h2>
            <dl>
              <dt>
                <kbd>/</kbd>
              </dt>
              <dd>search</dd>
              <dt>
                <kbd>↑↓</kbd>
              </dt>
              <dd>move</dd>
              <dt>
                <kbd>↵</kbd>
              </dt>
              <dd>jump in</dd>
              <dt>
                <kbd>1–6</kbd>
              </dt>
              <dd>filters</dd>
            </dl>
          </section>
        </aside>
      </div>
    </main>
  );
}

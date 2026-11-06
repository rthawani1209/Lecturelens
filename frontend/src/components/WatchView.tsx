"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, mediaUrl, type WatchData } from "@/lib/api";
import { timecode } from "@/lib/format";
import { Notes } from "./Notes";
import { Player, type PlayerHandle } from "./Player";
import { ScopeBand } from "./ScopeBand";
import { Transcript } from "./Transcript";
import styles from "./Watch.module.css";

// signed media links last 15 minutes; refresh well before that
const REFRESH_MS = 12 * 60 * 1000;

export function WatchView({ id }: { id: string }) {
  const params = useSearchParams();
  const router = useRouter();
  const [data, setData] = useState<WatchData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [time, setTime] = useState(Number(params.get("t")) || 0);
  const player = useRef<PlayerHandle>(null);

  const load = useCallback(
    () =>
      api.watch(id).then(
        (d) => {
          setData(d);
          setError(null);
          return d;
        },
        (e: Error) => {
          setError(
            e instanceof ApiError && (e.status === 404 || e.status === 422)
              ? "not-found"
              : e.message,
          );
          return null;
        },
      ),
    [id],
  );

  useEffect(() => {
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  const seek = useCallback((t: number) => {
    player.current?.seek(t);
    setTime(t);
  }, []);

  // keep ?t= in step so a copied URL lands on the same moment
  const shareUrl = useMemo(() => {
    if (typeof window === "undefined") return "";
    return `${window.location.origin}/watch/${id}?t=${Math.floor(time)}`;
  }, [id, time]);
  const [copied, setCopied] = useState(false);

  if (error === "not-found") {
    return (
      <main className={styles.page}>
        <div className={styles.missing}>
          <p className="label">Watch</p>
          <h1 className="display">
            This lecture doesn&apos;t exist, or isn&apos;t shared with you.
          </h1>
          <Link href="/watch">Back to all lectures</Link>
        </div>
      </main>
    );
  }

  if (error && !data) {
    return (
      <main className={styles.page}>
        <div className={styles.missing} role="alert">
          <h1 className="display">Couldn&apos;t load this lecture.</h1>
          <p>{error}</p>
          <button type="button" className={styles.primary} onClick={() => load()}>
            Try again
          </button>
        </div>
      </main>
    );
  }

  if (!data) {
    return (
      <main className={styles.page} aria-busy="true">
        <div className={styles.loadingTitle} />
        <div className={styles.loadingPlayer} />
      </main>
    );
  }

  const title = data.title.replace(/^Lecture \d+:\s*/, "");
  const length = data.duration_s ?? 0;

  return (
    <main className={styles.page}>
      <div className={styles.titleRow}>
        <div>
          <p className="label">
            <Link href={`/search?course=${data.course.id}`} className={styles.crumb}>
              {data.course.code || data.course.title}
            </Link>
            {data.week ? ` / Week ${data.week}` : ""} / Lecture {data.position}
          </p>
          <h1 className="display">{title}</h1>
        </div>
        <div className={styles.actions}>
          <Link href={`/study?lecture=${data.id}`} className={styles.primary}>
            Study this lecture
          </Link>
          <button
            type="button"
            className={styles.secondary}
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(shareUrl);
                setCopied(true);
                setTimeout(() => setCopied(false), 2000);
              } catch {
                router.replace(`/watch/${id}?t=${Math.floor(time)}`);
              }
            }}
          >
            {copied ? "Link copied" : `Share ${timecode(time)}`}
          </button>
        </div>
      </div>

      <div className={styles.columns}>
        <section className={styles.main} aria-label="Player">
          {data.status !== "ready" ? (
            <div className={styles.notReady} role="status">
              <p className="label">{data.status}</p>
              <p>
                {data.status === "failed"
                  ? "This lecture didn't finish processing."
                  : "This lecture is still being processed."}
              </p>
              <Link href={`/upload?lecture=${data.id}`}>Watch the pipeline</Link>
            </div>
          ) : (
            <Player
              ref={player}
              src={mediaUrl(data.video_url)}
              start={Number(params.get("t")) || 0}
              length={length}
              transcript={data.transcript}
              tag={currentTag(data, time)}
              onTime={setTime}
              onExpired={load}
            />
          )}
          <ScopeBand frames={data.frames} length={length} time={time} onSeek={seek} />
          <Filmstrip data={data} time={time} onSeek={seek} />
        </section>

        <aside className={styles.side}>
          <Transcript lines={data.transcript} time={time} onSeek={seek} />
          <Notes lectureId={data.id} time={time} onSeek={seek} />
        </aside>
      </div>
    </main>
  );
}

function currentTag(data: WatchData, t: number): string | null {
  let tag: string | null = null;
  for (const f of data.frames) {
    if (f.t_s > t) break;
    tag = f.tag;
  }
  return tag;
}

function Filmstrip({
  data,
  time,
  onSeek,
}: {
  data: WatchData;
  time: number;
  onSeek: (t: number) => void;
}) {
  // at most ~24 stops, evenly spread, so long lectures stay scannable
  const step = Math.max(1, Math.ceil(data.frames.length / 24));
  const frames = data.frames.filter((_, i) => i % step === 0);
  const current = frames.reduce((best, f, i) => (f.t_s <= time ? i : best), 0);
  return (
    <div className={styles.strip} role="group" aria-label="Boards and slides">
      {frames.map((f, i) => (
        <button
          key={f.t_s}
          type="button"
          className={i === current ? `${styles.thumb} ${styles.thumbOn}` : styles.thumb}
          onClick={() => onSeek(f.t_s)}
          aria-label={`Jump to ${timecode(f.t_s)}${f.tag ? `, ${f.tag}` : ""}`}
          aria-current={i === current ? "true" : undefined}
        >
          {/* eslint-disable-next-line @next/next/no-img-element -- signed private thumbnails */}
          <img src={mediaUrl(f.thumb_url) ?? ""} alt="" loading="lazy" />
          <span className="mono">
            <span>{timecode(f.t_s)}</span>
            <span>{f.tag}</span>
          </span>
        </button>
      ))}
    </div>
  );
}

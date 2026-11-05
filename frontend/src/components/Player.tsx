"use client";

import { useEffect, useImperativeHandle, useMemo, useRef, useState, type Ref } from "react";
import { position, timecode } from "@/lib/format";
import { Reticle } from "./Reticle";
import styles from "./Watch.module.css";

export type PlayerHandle = { seek: (t: number) => void; time: () => number };

const SPEEDS = [1, 1.25, 1.5, 1.75, 2, 0.75];

type Props = {
  ref?: Ref<PlayerHandle>;
  src: string | null;
  start: number;
  length: number;
  transcript: { start_s: number; end_s: number; text: string }[];
  tag: string | null;
  onTime: (t: number) => void;
  /** the signed link ran out; fetch a fresh one */
  onExpired: () => void;
};

/** WebVTT from the transcript, so captions come from the same text we search. */
function toVtt(lines: Props["transcript"]): string {
  const ts = (s: number) => {
    const d = new Date(Math.max(0, s) * 1000).toISOString();
    return d.substring(11, 23);
  };
  return (
    "WEBVTT\n\n" + lines.map((l) => `${ts(l.start_s)} --> ${ts(l.end_s)}\n${l.text}\n`).join("\n")
  );
}

export function Player({ ref, src, start, length, transcript, tag, onTime, onExpired }: Props) {
  const video = useRef<HTMLVideoElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const resumeAt = useRef<number | null>(start || null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(start);
  const [speed, setSpeed] = useState(1);
  const [captions, setCaptions] = useState(true);
  // 0 = fine, 1 = fetching a fresh link, 2 = gave up
  const [errors, setErrors] = useState(0);

  const vtt = useMemo(
    () => URL.createObjectURL(new Blob([toVtt(transcript)], { type: "text/vtt" })),
    [transcript],
  );
  useEffect(() => () => URL.revokeObjectURL(vtt), [vtt]);

  useImperativeHandle(ref, () => ({
    seek(t: number) {
      const to = Math.max(0, Math.min(t, length || t));
      const v = video.current;
      // before metadata loads (or if it never does) remember where to go
      if (v && v.readyState > 0) v.currentTime = to;
      else resumeAt.current = to;
      setTime(to);
      onTime(to);
    },
    time: () => video.current?.currentTime ?? 0,
  }));

  // The browser draws captions at the very bottom, under our control bar, so we
  // keep the track hidden (it still fires cue changes) and draw them ourselves.
  const [cue, setCue] = useState("");
  useEffect(() => {
    const track = video.current?.textTracks[0];
    if (!track) return;
    track.mode = "hidden";
    const show = () =>
      setCue(
        Array.from(track.activeCues ?? [])
          .map((c) => (c as VTTCue).text)
          .join("\n"),
      );
    track.addEventListener("cuechange", show);
    return () => track.removeEventListener("cuechange", show);
  }, [vtt]);

  useEffect(() => {
    if (video.current) video.current.playbackRate = speed;
  }, [speed]);

  function toggle() {
    const v = video.current;
    if (!v) return;
    if (v.paused) v.play().catch(() => setPlaying(false));
    else v.pause();
  }

  function skip(by: number) {
    const v = video.current;
    if (v) v.currentTime = Math.max(0, Math.min(v.currentTime + by, v.duration || length));
  }

  function cycleSpeed(dir = 1) {
    setSpeed((s) => SPEEDS[(SPEEDS.indexOf(s) + dir + SPEEDS.length) % SPEEDS.length]);
  }

  function fullscreen() {
    if (document.fullscreenElement) document.exitFullscreen();
    else box.current?.requestFullscreen?.();
  }

  // J/K/L like YouTube, plus space, C for captions, F for full screen, < > for speed
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const el = e.target as HTMLElement;
      if (
        ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) ||
        e.metaKey ||
        e.ctrlKey ||
        e.altKey
      )
        return;
      const k = e.key.toLowerCase();
      if (k === "k" || (k === " " && el.tagName !== "BUTTON")) toggle();
      else if (k === "j") skip(-10);
      else if (k === "l") skip(10);
      else if (k === "arrowleft") skip(-5);
      else if (k === "arrowright") skip(5);
      else if (k === "c") setCaptions((c) => !c);
      else if (k === "f") fullscreen();
      else if (e.key === ">") cycleSpeed(1);
      else if (e.key === "<") cycleSpeed(-1);
      else return;
      e.preventDefault();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const pct = position(time, length);

  return (
    <div className={styles.player} ref={box}>
      <Reticle inset={16}>
        <video
          ref={video}
          src={src ?? undefined}
          className={styles.video}
          preload="metadata"
          playsInline
          crossOrigin="anonymous"
          onClick={toggle}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onLoadedMetadata={(e) => {
            const v = e.currentTarget;
            if (resumeAt.current) v.currentTime = resumeAt.current;
            resumeAt.current = null;
            v.playbackRate = speed;
            setErrors(0);
          }}
          onTimeUpdate={(e) => {
            if (e.currentTarget.readyState === 0) return;
            setTime(e.currentTarget.currentTime);
            onTime(e.currentTarget.currentTime);
          }}
          onError={() => {
            // most likely the signed link expired mid-lecture: get a new one and carry on
            resumeAt.current = video.current?.currentTime ?? time;
            // one fresh link usually fixes it; don't loop if the file itself is the problem
            setErrors((n) => {
              if (n === 0) onExpired();
              return Math.min(n + 1, 2);
            });
          }}
        >
          <track kind="captions" srcLang="en" label="English" src={vtt} default />
        </video>
      </Reticle>
      {tag && <span className={`mono ${styles.onScreen}`}>{tag} · auto-tagged</span>}
      {captions && cue && (
        <div className={styles.caption} data-testid="caption">
          {cue}
        </div>
      )}
      {errors > 0 && (
        <div className={styles.failed} role="alert">
          {errors < 2
            ? "Reconnecting the video…"
            : video.current?.canPlayType("video/mp4") === ""
              ? "This browser can't play MP4 video. The transcript and frames still work."
              : "This video can't be played right now. The transcript and frames still work."}
        </div>
      )}
      <div className={styles.controls}>
        <div
          className={styles.progress}
          role="slider"
          tabIndex={0}
          aria-label="Seek"
          aria-valuemin={0}
          aria-valuemax={Math.round(length)}
          aria-valuenow={Math.round(time)}
          aria-valuetext={timecode(time)}
          onClick={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            const t = ((e.clientX - r.left) / r.width) * length;
            if (video.current) video.current.currentTime = t;
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
              e.stopPropagation();
              e.preventDefault();
              skip(e.key === "ArrowLeft" ? -5 : 5);
            }
          }}
        >
          <div className={styles.progressDone} style={{ width: pct }} />
          <div className={styles.progressKnob} style={{ left: pct }} />
        </div>
        <div className={styles.buttons}>
          <button
            type="button"
            className={styles.ctl}
            onClick={() => skip(-10)}
            aria-label="Back 10 seconds (J)"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
              <path
                d="M11 7 6 12l5 5M18 7l-5 5 5 5"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
          <button
            type="button"
            className={styles.ctl}
            onClick={toggle}
            aria-label={playing ? "Pause (K)" : "Play (K)"}
          >
            {playing ? (
              <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M8 5v14M16 5v14"
                  stroke="currentColor"
                  strokeWidth="2.4"
                  strokeLinecap="round"
                />
              </svg>
            ) : (
              <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M7 5v14l12-7z" fill="currentColor" />
              </svg>
            )}
          </button>
          <button
            type="button"
            className={styles.ctl}
            onClick={() => skip(10)}
            aria-label="Forward 10 seconds (L)"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
              <path
                d="m13 7 5 5-5 5M6 7l5 5-5 5"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
          <span className={`mono ${styles.clock}`}>
            <span>{timecode(time)}</span> / {timecode(length)}
          </span>
          <span className={styles.grow} />
          <button
            type="button"
            className={`mono ${styles.ctl} ${styles.speed}`}
            onClick={() => cycleSpeed(1)}
            aria-label={`Playback speed ${speed}x`}
          >
            {speed}×
          </button>
          <button
            type="button"
            className={captions ? `${styles.ctl} ${styles.ctlOn}` : styles.ctl}
            onClick={() => setCaptions((c) => !c)}
            aria-label={captions ? "Hide captions (C)" : "Show captions (C)"}
            aria-pressed={captions}
          >
            <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true">
              <rect
                x="3"
                y="5"
                width="18"
                height="14"
                rx="3"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
              />
              <path
                d="M10 10.5a2 2 0 1 0 0 3M16.5 10.5a2 2 0 1 0 0 3"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.6"
              />
            </svg>
          </button>
          <button
            type="button"
            className={styles.ctl}
            onClick={fullscreen}
            aria-label="Full screen (F)"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
              <path
                d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
              />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}

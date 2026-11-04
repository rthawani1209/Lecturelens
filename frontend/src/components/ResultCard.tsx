import Link from "next/link";
import { type Hit, mediaUrl } from "@/lib/api";
import { highlight, timecode } from "@/lib/format";
import { Reticle } from "./Reticle";
import { TraceBar } from "./TraceBar";
import styles from "./Search.module.css";

const CHANNELS = [
  { id: "keyword", label: "Keyword", color: "var(--ch-keyword)" },
  { id: "meaning", label: "Meaning", color: "var(--ch-meaning)" },
  { id: "ocr", label: "Slide text", color: "var(--ch-ocr)" },
  { id: "visual", label: "Visual", color: "var(--ch-visual)" },
];

export function watchHref(hit: Pick<Hit, "lecture_id" | "jump_s">): string {
  return `/watch/${hit.lecture_id}?t=${Math.floor(hit.jump_s)}`;
}

type Props = { hit: Hit; query: string; selected: boolean; index: number };

export function ResultCard({ hit, query, selected, index }: Props) {
  const thumb = mediaUrl(hit.thumb_url);
  const title = hit.lecture_title.replace(/^Lecture \d+:\s*/, "");
  const sentence = hit.sentence || hit.text;
  return (
    <Link
      href={watchHref(hit)}
      className={selected ? `${styles.card} ${styles.cardOn} rise` : `${styles.card} rise`}
      style={{ animationDelay: `${index * 40}ms` }}
      data-result={index}
    >
      <Reticle>
        <div className={styles.thumb}>
          {thumb ? (
            // eslint-disable-next-line @next/next/no-img-element -- private thumbnails, no optimizer
            <img
              src={thumb}
              alt={`Frame from ${title} at ${timecode(hit.frame_t ?? hit.jump_s)}`}
            />
          ) : (
            <div className={styles.noThumb}>no frame</div>
          )}
          <span className={`mono ${styles.time}`}>▶ {timecode(hit.jump_s)}</span>
          {hit.tag && <span className={`mono ${styles.tag}`}>{hit.tag}</span>}
        </div>
      </Reticle>
      <div className={styles.body}>
        <div className={styles.head}>
          <span className={styles.title}>{title}</span>
          <span className={`mono ${styles.meta}`}>
            {hit.week ? `Week ${hit.week} · ` : ""}L{hit.lecture_position}
          </span>
        </div>
        <p className={styles.quote}>
          “
          {highlight(sentence, query).map((p, i) =>
            p.hit ? <mark key={i}>{p.text}</mark> : <span key={i}>{p.text}</span>,
          )}
          ”
        </p>
        <ul className={styles.channels} aria-label="Found by">
          {CHANNELS.map((c) => {
            const on = hit.matched_by.includes(c.id);
            return (
              <li
                key={c.id}
                className={on ? `mono ${styles.ch} ${styles.chOn}` : `mono ${styles.ch}`}
              >
                <span style={{ background: on ? c.color : "transparent" }} aria-hidden="true" />
                {c.label}
                {!on && <span className="sr-only"> (no match)</span>}
              </li>
            );
          })}
        </ul>
        <TraceBar at={hit.jump_s} length={hit.lecture_duration_s} />
      </div>
    </Link>
  );
}

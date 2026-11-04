/** 1599.4 -> "26:39", 3725 -> "1:02:05" */
export function timecode(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

/** Where t sits in a lecture, as a CSS percentage clamped to the bar. */
export function position(t: number, length: number | null | undefined): string {
  if (!length || length <= 0) return "0%";
  return `${Math.min(100, Math.max(0, (t / length) * 100)).toFixed(1)}%`;
}

const STOP = new Set(
  "a an and are as at be but by can do does for from how i in is it of on or so that the this to was what when where which why will with you".split(
    " ",
  ),
);

export type Part = { text: string; hit: boolean };

/** Split a sentence into runs, marking the words that appear in the query. */
export function highlight(sentence: string, query: string): Part[] {
  const want = new Set(
    query
      .toLowerCase()
      .split(/[^\p{L}\p{N}']+/u)
      .filter((w) => w.length > 1 && !STOP.has(w)),
  );
  const parts: Part[] = [];
  for (const token of sentence.split(/([\p{L}\p{N}']+)/u)) {
    if (!token) continue;
    const word = token.toLowerCase();
    // match "weights" for "weight" and the other way round
    const hit = want.has(word) || want.has(word.replace(/s$/, "")) || want.has(`${word}s`);
    const last = parts[parts.length - 1];
    if (last && (last.hit === hit || (!/[\p{L}\p{N}]/u.test(token) && last.hit))) {
      last.text += token;
    } else {
      parts.push({ text: token, hit });
    }
  }
  // a trailing space or comma shouldn't sit inside the highlight
  return parts.flatMap((p) => {
    const m = p.hit ? p.text.match(/^(.*?[\p{L}\p{N}'])(\P{L}*)$/u) : null;
    return m && m[2]
      ? [
          { text: m[1], hit: true },
          { text: m[2], hit: false },
        ]
      : [p];
  });
}

/** "Lecture 13: Dijkstra" at position 13 -> "L13 · Dijkstra", for tight lists. */
export function shortTitle(title: string, pos: number): string {
  const bare = title.replace(/^(lecture|lec\.?)\s*\d+\s*[:.\-–]\s*/i, "");
  return `L${pos} · ${bare}`;
}

/** Only same-site paths, so ?next= can't bounce people to another site. */
export function safeNext(next: string | null): string {
  // a backslash counts as a slash in browsers, so /\evil.com is the same as //evil.com
  return next && /^\/(?![/\\])/.test(next) ? next : "/";
}

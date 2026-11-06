// Resumable upload client for the API's chunked PUT protocol (same idea as
// Google Cloud Storage resumable uploads):
//   PUT url  Content-Range: bytes a-b/N   -> 308 + Range: bytes=0-x while unfinished
//   PUT url  Content-Range: bytes */N     -> "how much do you have?"
//   201/200 when the last byte lands.

export type Progress = { sent: number; total: number };

/** What the server says when the last byte lands. `duplicate` means the course
 * already had this exact video and `lecture_id` is that existing lecture. */
export type Done = { lecture_id?: string; duplicate?: boolean };

const finished = (res: Response): Promise<Done> => res.json().catch(() => ({}));

export class UploadError extends Error {
  /** true when the server turned the file down (not a network problem), so retrying won't help */
  constructor(
    message: string,
    readonly refused = false,
  ) {
    super(message);
  }
}

type Fetch = typeof fetch;

// the link lasts a day and the server clears half-sent files after that
const EXPIRED =
  "This upload was left too long and has expired. Choose the file again to start over.";

/** Bytes the server already has, from a 308's Range header ("bytes=0-x"). */
export function storedBytes(res: Response): number {
  const m = /bytes=0-(\d+)/.exec(res.headers.get("Range") ?? "");
  return m ? Number(m[1]) + 1 : 0;
}

async function ask(
  url: string,
  total: number,
  signal: AbortSignal,
  f: Fetch,
): Promise<{ sent: number; done?: Done }> {
  const res = await f(url, {
    method: "PUT",
    headers: { "Content-Range": `bytes */${total}` },
    signal,
  });
  if (res.status === 200 || res.status === 201) return { sent: total, done: await finished(res) };
  if (res.status === 308) return { sent: storedBytes(res) };
  if (res.status === 403 || res.status === 404) throw new UploadError(EXPIRED, true);
  throw new UploadError(`upload status check failed (${res.status})`);
}

const wait = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(t);
      reject(new DOMException("aborted", "AbortError"));
    });
  });

/**
 * Send `file` in chunks. Network errors don't lose progress: it asks the server how
 * much it has and carries on from there, retrying with backoff a few times.
 */
export async function upload(
  url: string,
  file: Blob,
  opts: {
    chunk: number;
    signal: AbortSignal;
    onProgress?: (p: Progress) => void;
    retries?: number;
    fetchImpl?: Fetch;
    backoffMs?: number;
  },
): Promise<Done> {
  const f = opts.fetchImpl ?? fetch;
  const total = file.size;
  const retries = opts.retries ?? 5;
  // if the status check fails, start from 0; the server answers with where it really is
  const first = await ask(url, total, opts.signal, f).catch((e) => {
    if (opts.signal.aborted) throw e;
    return { sent: 0, done: undefined };
  });
  let sent = first.sent;
  let done: Done | undefined = first.done;
  let failures = 0;
  opts.onProgress?.({ sent, total });

  while (sent < total) {
    opts.signal.throwIfAborted();
    const end = Math.min(sent + opts.chunk, total) - 1;
    try {
      const res = await f(url, {
        method: "PUT",
        headers: { "Content-Range": `bytes ${sent}-${end}/${total}` },
        body: file.slice(sent, end + 1),
        signal: opts.signal,
      });
      if (res.status === 200 || res.status === 201) {
        done = await finished(res);
        sent = total;
      } else if (res.status === 308) {
        sent = storedBytes(res);
      } else if (res.status === 403 || res.status === 404) {
        throw new UploadError(EXPIRED, true);
      } else if (res.status >= 400 && res.status < 500) {
        const body = await res.json().catch(() => ({}));
        throw new UploadError(body.detail ?? `upload refused (${res.status})`, true);
      } else {
        throw new Error(`server error ${res.status}`);
      }
      failures = 0;
      opts.onProgress?.({ sent, total });
    } catch (e) {
      if (opts.signal.aborted || e instanceof UploadError) throw e;
      if (++failures > retries) throw new UploadError("the connection keeps dropping; try again");
      await wait((opts.backoffMs ?? 1000) * 2 ** (failures - 1), opts.signal);
      const now = await ask(url, total, opts.signal, f).catch(() => ({ sent, done }));
      sent = now.sent;
      done = now.done ?? done;
    }
  }
  return done ?? {};
}

import { describe, expect, it } from "vitest";
import { upload, UploadError } from "./upload";

/** A fake server speaking the chunked PUT protocol, that can drop a request. */
function server(total: number, dropOn: number[] = []) {
  let have = 0;
  let call = 0;
  const seen: string[] = [];
  const impl = (async (_url: string, init: RequestInit) => {
    call++;
    const range = (init.headers as Record<string, string>)["Content-Range"];
    seen.push(range);
    if (dropOn.includes(call)) {
      // the chunk arrived but the reply got lost
      const m = /bytes (\d+)-(\d+)/.exec(range);
      if (m) have = Math.max(have, Number(m[2]) + 1);
      throw new TypeError("network down");
    }
    const m = /bytes (\d+)-(\d+)\/(\d+)/.exec(range);
    if (m && Number(m[1]) === have) have = Number(m[2]) + 1;
    if (have >= total) return new Response(null, { status: 201 });
    return new Response(null, {
      status: 308,
      headers: have ? { Range: `bytes=0-${have - 1}` } : {},
    });
  }) as typeof fetch;
  return { impl, seen, have: () => have };
}

const blob = (n: number) => new Blob([new Uint8Array(n)]);

describe("upload", () => {
  it("sends every chunk in order", async () => {
    const s = server(25);
    const progress: number[] = [];
    await upload("/u", blob(25), {
      chunk: 10,
      signal: new AbortController().signal,
      fetchImpl: s.impl,
      onProgress: (p) => progress.push(p.sent),
    });
    expect(s.seen).toEqual(["bytes */25", "bytes 0-9/25", "bytes 10-19/25", "bytes 20-24/25"]);
    expect(progress.at(-1)).toBe(25);
  });

  it("asks where it got to after a dropped connection and resumes there", async () => {
    const s = server(30, [3]);
    await upload("/u", blob(30), {
      chunk: 10,
      signal: new AbortController().signal,
      fetchImpl: s.impl,
      backoffMs: 1,
    });
    expect(s.seen).toEqual([
      "bytes */30",
      "bytes 0-9/30",
      "bytes 10-19/30", // reply lost
      "bytes */30", // server says it has 0-19
      "bytes 20-29/30",
    ]);
    expect(s.have()).toBe(30);
  });

  it("gives up after too many failures", async () => {
    const s = server(10, [2, 3, 4, 5]);
    await expect(
      upload("/u", blob(10), {
        chunk: 10,
        retries: 1,
        signal: new AbortController().signal,
        fetchImpl: s.impl,
        backoffMs: 1,
      }),
    ).rejects.toBeInstanceOf(UploadError);
  });

  it("stops when cancelled", async () => {
    const ctrl = new AbortController();
    ctrl.abort();
    const s = server(10);
    await expect(
      upload("/u", blob(10), { chunk: 5, signal: ctrl.signal, fetchImpl: s.impl }),
    ).rejects.toBeTruthy();
  });
  it("stops at once when the server refuses the file", async () => {
    let puts = 0;
    const impl = (async (_url: string, init: RequestInit) => {
      const range = (init.headers as Record<string, string>)["Content-Range"];
      if (range.startsWith("bytes */")) return new Response(null, { status: 308 });
      puts++;
      return Response.json({ detail: "This file isn't a video." }, { status: 415 });
    }) as typeof fetch;
    const err = await upload("/u", blob(25), {
      chunk: 10,
      signal: new AbortController().signal,
      fetchImpl: impl,
      backoffMs: 1,
    }).catch((e) => e);
    expect(err).toBeInstanceOf(UploadError);
    expect(err.refused).toBe(true);
    expect(err.message).toBe("This file isn't a video.");
    expect(puts).toBe(1); // no retries
  });
  it("cancelling during the first status check keeps the error an abort", async () => {
    const ctl = new AbortController();
    const impl = ((_url: string, init: RequestInit) =>
      new Promise((_resolve, reject) => {
        init.signal?.addEventListener("abort", () =>
          reject(new DOMException("aborted", "AbortError")),
        );
      })) as typeof fetch;
    const progress: number[] = [];
    const done = upload("/u", blob(25), {
      chunk: 10,
      signal: ctl.signal,
      fetchImpl: impl,
      onProgress: (p) => progress.push(p.sent),
    });
    ctl.abort();
    await expect(done).rejects.toThrow("aborted");
    expect(progress).toEqual([]); // nothing claims we went back to 0
  });
  it("returns the lecture the server settled on", async () => {
    const impl = (async (_url: string, init: RequestInit) => {
      const range = (init.headers as Record<string, string>)["Content-Range"];
      if (range.startsWith("bytes */")) return new Response(null, { status: 308 });
      return Response.json({ lecture_id: "existing", duplicate: true }, { status: 200 });
    }) as typeof fetch;
    const done = await upload("/u", blob(5), {
      chunk: 10,
      signal: new AbortController().signal,
      fetchImpl: impl,
    });
    expect(done).toEqual({ lecture_id: "existing", duplicate: true });
  });
});

"""Check a running LectureLens site end to end, the way a visitor uses it:
sign in with the demo button, upload a video, wait for it to be processed,
search it, and play it back.

  python3 deploy/smoke.py https://1.2.3.4.sslip.io clip.mp4 "a phrase said in the clip"

Standard library only, so it runs on a bare server. Pass --insecure for a local
self-signed certificate.
"""

import argparse
import http.cookiejar
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


class Site:
    def __init__(self, base: str, insecure: bool):
        self.base = base.rstrip("/")
        ctx = ssl.create_default_context()
        if insecure:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
            urllib.request.HTTPSHandler(context=ctx),
        )

    def call(self, method, path, body=None, data=None, headers=None, expect=(200,)):
        headers = dict(headers or {})
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            resp = self.opener.open(req, timeout=120)
            status, raw, hdrs = resp.status, resp.read(), resp.headers
        except urllib.error.HTTPError as e:
            status, raw, hdrs = e.code, e.read(), e.headers
        if status not in expect:
            sys.exit(f"FAIL {method} {path}: {status} {raw[:300]!r}")
        if "json" in (hdrs.get("Content-Type") or ""):
            return json.loads(raw)
        return raw


def step(msg):
    print(f"ok  {msg}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("video")
    ap.add_argument("phrase", help="something said in the video, to search for")
    ap.add_argument("--insecure", action="store_true")
    ap.add_argument("--timeout", type=int, default=1800, help="seconds to wait for processing")
    args = ap.parse_args()
    site = Site(args.base, args.insecure)

    page = site.call("GET", "/")
    assert b"LectureLens" in page, "home page doesn't look right"
    # the home page is rendered on the server, which has to reach the API itself
    assert b"reach the LectureLens API" not in page, "home page can't reach the API"
    step("home page, with courses from the API")
    models = site.call("GET", "/api/health")["models"]
    # a configured TF Serving that isn't answering means the site quietly fell back to
    # NumPy copies; "not configured" is the ARM setup, which uses them on purpose
    bad = {k: v for k, v in models.items() if v not in ("AVAILABLE", "not configured")}
    assert not bad, f"TF Serving isn't serving: {bad}"
    step(f"api health, models: {models}")
    assert site.call("GET", "/api/auth/providers").get("demo"), "demo sign-in is off"
    me = site.call("POST", "/api/auth/demo")
    step(f"demo sign-in as {me['email']}")

    course = site.call("POST", "/api/courses", {"title": "Smoke test"}, expect=(201,))["id"]
    size = os.path.getsize(args.video)
    up = site.call(
        "POST",
        f"/api/courses/{course}/lectures",
        {"title": "Smoke test lecture", "filename": os.path.basename(args.video), "size": size},
        expect=(201,),
    )
    with open(args.video, "rb") as f:
        first = 0
        while first < size:
            chunk = f.read(up["chunk_size"])
            last = first + len(chunk) - 1
            site.call(
                "PUT",
                "/api" + up["upload_url"],
                data=chunk,
                headers={"Content-Range": f"bytes {first}-{last}/{size}"},
                expect=(200, 201, 308),
            )
            first = last + 1
    lecture = up["lecture_id"]
    step(f"uploaded {size / 1e6:.1f} MB")

    t0 = time.time()
    while True:
        lec = site.call("GET", f"/api/lectures/{lecture}")
        if lec["status"] == "ready":
            break
        if lec["status"] == "failed":
            sys.exit(f"FAIL processing: {json.dumps(lec['stages'])}")
        if time.time() - t0 > args.timeout:
            sys.exit(f"FAIL still {lec['status']} after {args.timeout}s")
        time.sleep(10)
    step(f"processed in {time.time() - t0:.0f}s")

    q = urllib.parse.urlencode({"q": args.phrase, "course": course})
    hits = site.call("GET", f"/api/search?{q}")["hits"]
    assert hits and hits[0]["lecture_id"] == lecture, f"search found nothing for {args.phrase!r}"
    step(f"search jumps to {hits[0]['start_s']:.0f}s")

    watch = site.call("GET", f"/api/lectures/{lecture}/watch")
    assert watch["transcript"], "no transcript"
    video = site.call(
        "GET", "/api" + watch["video_url"], headers={"Range": "bytes=0-1023"}, expect=(206,)
    )
    assert len(video) == 1024
    step(f"watch page: {len(watch['transcript'])} transcript lines, video streams")

    site.call("DELETE", f"/api/lectures/{lecture}", expect=(204,))
    site.call("DELETE", f"/api/courses/{course}", expect=(204, 404, 405))
    step("cleaned up")


if __name__ == "__main__":
    main()

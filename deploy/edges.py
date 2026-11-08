"""Edge cases against a running LectureLens site, from outside it.

  python3 deploy/edges.py https://1.2.3.4.sslip.io clip.mp4

Bad files, size limit, nonsense and empty searches, missing pages, signed-out
writes, and a cut-off video that should fail with a plain message. Uses two of
the day's upload slots for this IP (the PDF gives its slot back).
"""

import argparse
import json
import sys
import time
import urllib.parse
import uuid

from smoke import Site, step


def upload(site, course, name, data, expect_put=(200, 201, 308)):
    up = site.call(
        "POST",
        f"/api/courses/{course}/lectures",
        {"title": name, "filename": name, "size": len(data)},
        expect=(201,),
    )
    res = site.call(
        "PUT",
        "/api" + up["upload_url"],
        data=data,
        headers={"Content-Range": f"bytes 0-{len(data) - 1}/{len(data)}"},
        expect=expect_put,
    )
    return up["lecture_id"], res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("video", help="a real video; its first 60 KB make the cut-off file")
    ap.add_argument("--insecure", action="store_true")
    args = ap.parse_args()
    site = Site(args.base, args.insecure)

    for path in ["/", "/search?q=dijkstra", "/study", "/upload", "/signin"]:
        assert b"LectureLens" in site.call("GET", path), f"{path} doesn't look right"
    step("every page loads")
    missing = str(uuid.uuid4())
    site.call("GET", f"/api/lectures/{missing}", expect=(404,))
    site.call("GET", f"/watch/{missing}", expect=(200, 404))
    site.call("GET", "/no-such-page", expect=(404,))
    step("missing lectures and pages say so")
    site.call("POST", "/api/courses", {"title": "nope"}, expect=(401,))
    step("signed out can't create anything")

    public = site.call("GET", "/api/courses/public")
    codes = sorted(c["code"] for c in public)
    assert {"6.006", "6.100L", "18.06"} <= set(codes), f"demo courses missing: {codes}"
    ready = sum(c["ready_count"] for c in public)
    step(f"demo courses listed: {codes}, {ready} lectures ready so far")

    site.call("POST", "/api/auth/demo")
    for q in ["xqzvbnm wibble", "zxqv blorft"]:
        hits = site.call("GET", "/api/search?" + urllib.parse.urlencode({"q": q}))["hits"]
        assert not hits, f"{q!r} found {len(hits)} results"
    site.call("GET", "/api/search?q=", expect=(422,))
    site.call("GET", "/api/search?" + urllib.parse.urlencode({"q": "x" * 301}), expect=(422,))
    step("nonsense, empty and too-long searches")

    course = site.call("POST", "/api/courses", {"title": "Edge cases"}, expect=(201,))["id"]
    site.call(
        "POST",
        f"/api/courses/{course}/lectures",
        {"title": "huge", "filename": "huge.mp4", "size": 50 * 1024**3},
        expect=(413,),
    )
    site.call(
        "POST",
        f"/api/courses/{course}/lectures",
        {"title": "notes", "filename": "notes.pdf", "size": 5000},
        expect=(415,),
    )
    step("too big and wrong extension refused before upload")
    lid, res = upload(site, course, "notes.mp4", b"%PDF-1.7\n" + b"x" * 5000, expect_put=(415,))
    assert "isn't a video" in res["detail"], res
    site.call("GET", f"/api/lectures/{lid}", expect=(404,))
    step("a PDF renamed .mp4 is refused by its first bytes")

    with open(args.video, "rb") as f:
        head = f.read(60_000)
    lid, _ = upload(site, course, "cut-off.mp4", head)
    t0 = time.time()
    while (lec := site.call("GET", f"/api/lectures/{lid}"))["status"] != "failed":
        if lec["status"] == "ready" or time.time() - t0 > 600:
            sys.exit(f"FAIL cut-off video ended up {lec['status']}")
        time.sleep(5)
    errors = [s["error"] for s in lec["stages"] if s["error"]]
    assert errors == ["This file isn't a playable video."], json.dumps(lec["stages"])
    retried = site.call("POST", f"/api/lectures/{lid}/retry")
    assert retried["status"] != "failed", retried["status"]
    step("a cut-off video fails with a plain message, and can be retried")

    site.call("DELETE", f"/api/lectures/{lid}", expect=(204,))
    site.call("DELETE", f"/api/courses/{course}", expect=(204,))
    step("cleaned up")


if __name__ == "__main__":
    main()

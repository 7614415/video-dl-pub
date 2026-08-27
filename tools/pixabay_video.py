#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pixabay video fetcher, run from a GitHub runner.

Locally this is rate-limited to death (HTTP 403 after ~100 requests) and the
search payload only exposes the low-res *_tiny.mp4* preview. From a clean
runner IP we can probe the higher-resolution siblings of the same asset and
take the best one that actually resolves.

Pixabay Content License: free for commercial use, no attribution required.
"""
import argparse, json, os, re, subprocess, sys, time
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
HDRS = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"}
BOOT = re.compile(r'/bootstrap/([0-9a-f]{64})\.json')
MP4 = re.compile(r'https://cdn\.pixabay\.com/[^"\s\\]+\.mp4')
# best -> worst; Pixabay names its variants by this suffix
LADDER = ["_large.mp4", "_medium.mp4", "_small.mp4", "_tiny.mp4"]


def get(url, timeout=45):
    req = urllib.request.Request(url, headers=HDRS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def head_ok(url):
    """HEAD is often refused; a 1-byte ranged GET is the reliable probe."""
    p = subprocess.run(["curl", "-s", "-o", os.devnull, "-w", "%{http_code} %{size_download}",
                        "-m", "25", "-A", UA, "-H", "Referer: https://pixabay.com/",
                        "-r", "0-1", url], capture_output=True, text=True)
    parts = p.stdout.split()
    return len(parts) == 2 and parts[0] in ("200", "206")


def upgrade(url):
    """Given any variant URL, return the highest resolution that resolves."""
    base = url
    for suf in LADDER:
        if url.endswith(suf):
            base = url[: -len(suf)]
            break
    else:
        return url
    for suf in LADDER:
        cand = base + suf
        if head_ok(cand):
            return cand
        time.sleep(0.4)
    return url


def search(query, count):
    page = get("https://pixabay.com/videos/search/%s/" % urllib.parse.quote(query)).decode(
        "utf-8", "ignore")
    m = BOOT.search(page)
    if not m:
        sys.exit("no bootstrap payload found on search page")
    data = get("https://pixabay.com/bootstrap/%s.json" % m.group(1)).decode("utf-8", "ignore")
    urls, seen = [], set()
    for u in MP4.findall(data):
        key = re.sub(r"_(large|medium|small|tiny)\.mp4$", "", u)
        if key in seen:
            continue
        seen.add(key)
        urls.append(u)
    print("search %r -> %d unique assets" % (query, len(urls)), flush=True)
    return urls[:count]


def safe(s, n=60):
    return (re.sub(r"[^\w .\-()]+", "_", str(s)).strip()[:n] or "clip")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", required=True, help="comma separated")
    ap.add_argument("--per", type=int, default=14)
    ap.add_argument("--out", default="out")
    a = ap.parse_args()

    manifest, res_seen = [], {}
    for q in [x.strip() for x in a.queries.split(",") if x.strip()]:
        d = os.path.join(a.out, safe(q).replace(" ", "_"))
        os.makedirs(d, exist_ok=True)
        for i, u in enumerate(search(q, a.per), 1):
            hi = upgrade(u)
            dst = os.path.join(d, "%02d_%s" % (i, safe(os.path.basename(hi))))
            r = subprocess.run(["curl", "-sL", "--fail", "-m", "300", "-A", UA,
                                "-H", "Referer: https://pixabay.com/", hi, "-o", dst])
            if r.returncode != 0 or not os.path.exists(dst) or os.path.getsize(dst) < 50000:
                if os.path.exists(dst):
                    os.remove(dst)
                print("  fail %s" % os.path.basename(hi), flush=True)
                continue
            got = re.search(r"_(large|medium|small|tiny)\.mp4$", hi)
            tag = got.group(1) if got else "?"
            res_seen[tag] = res_seen.get(tag, 0) + 1
            manifest.append(dict(query=q, file=os.path.relpath(dst, a.out),
                                 url=hi, variant=tag))
            print("  [%s] %s" % (tag, os.path.basename(dst)[:56]), flush=True)
            time.sleep(0.6)

    json.dump(manifest, open(os.path.join(a.out, "MANIFEST.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("variants obtained:", res_seen, flush=True)
    print("DONE: %d clips" % len(manifest), flush=True)
    if not manifest:
        sys.exit("nothing downloaded")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pexels video/photo fetcher, run from a GitHub runner.

Pexels returns HTTP 403 to the operator's network, and unlike Pixabay its
search pages embed the *real* file links (videos.pexels.com/video-files/...)
at full resolution rather than a preview. No API key required for this path.

Pexels License: free for commercial and non-commercial use, no attribution
required (crediting the photographer is appreciated). Do not resell the files
as-is, and do not present identifiable people in a defamatory way.
"""
import argparse, json, os, re, subprocess, sys, time
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
HDRS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9"}

VIDEO_FILE = re.compile(
    r'https://videos\.pexels\.com/video-files/\d+/[\w\-]+?\.mp4')
RES = re.compile(r'_(\d{3,4})_(\d{3,4})_(\d+)fps', re.I)


def get(url, timeout=60):
    req = urllib.request.Request(url, headers=HDRS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def pick_best(urls):
    """Group variants of the same asset id, keep the one closest to 1080p."""
    by_id = {}
    for u in urls:
        m = re.search(r"/video-files/(\d+)/", u)
        if not m:
            continue
        by_id.setdefault(m.group(1), []).append(u)

    def score(u):
        m = RES.search(u)
        if not m:
            return -1
        w, h = int(m.group(1)), int(m.group(2))
        # prefer exactly 1080p, then anything below 4K, then the rest
        if h == 1080:
            return 1000
        if 700 <= h < 1080:
            return 800 + h
        if h > 1080:
            return 600 - (h - 1080) / 10.0
        return h
    return {i: sorted(v, key=score, reverse=True)[0] for i, v in by_id.items()}


def search(query, count, pages=2):
    found = []
    for page in range(1, pages + 1):
        url = "https://www.pexels.com/search/videos/%s/?page=%d" % (
            urllib.parse.quote(query), page)
        try:
            html = get(url)
        except Exception as e:
            print("  page %d failed: %s" % (page, str(e)[:70]), flush=True)
            continue
        hits = VIDEO_FILE.findall(html.replace("\\/", "/"))
        print("  page %d -> %d raw links" % (page, len(hits)), flush=True)
        found += hits
        time.sleep(1.2)
    best = pick_best(found)
    print("search %r -> %d unique assets" % (query, len(best)), flush=True)
    return list(best.values())[:count]


def safe(s, n=64):
    return (re.sub(r"[^\w .\-()]+", "_", str(s)).strip()[:n] or "clip")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", required=True)
    ap.add_argument("--per", type=int, default=12)
    ap.add_argument("--pages", type=int, default=2)
    ap.add_argument("--out", default="out")
    a = ap.parse_args()

    manifest, sizes = [], {}
    for q in [x.strip() for x in a.queries.split(",") if x.strip()]:
        d = os.path.join(a.out, safe(q).replace(" ", "_"))
        os.makedirs(d, exist_ok=True)
        for i, u in enumerate(search(q, a.per, a.pages), 1):
            dst = os.path.join(d, "%02d_%s" % (i, safe(os.path.basename(u))))
            r = subprocess.run(["curl", "-sL", "--fail", "-m", "400", "-A", UA,
                                "-H", "Referer: https://www.pexels.com/", u, "-o", dst])
            if r.returncode != 0 or not os.path.exists(dst) or os.path.getsize(dst) < 50000:
                if os.path.exists(dst):
                    os.remove(dst)
                print("  fail %s" % os.path.basename(u)[:50], flush=True)
                continue
            m = RES.search(u)
            tag = "%sx%s" % (m.group(1), m.group(2)) if m else "?"
            sizes[tag] = sizes.get(tag, 0) + 1
            manifest.append(dict(query=q, file=os.path.relpath(dst, a.out), url=u, res=tag))
            print("  [%s] %s" % (tag, os.path.basename(dst)[:52]), flush=True)
            time.sleep(0.5)

    json.dump(manifest, open(os.path.join(a.out, "MANIFEST.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("resolutions obtained:", sizes, flush=True)
    print("DONE: %d clips" % len(manifest), flush=True)
    if not manifest:
        sys.exit("nothing downloaded")


if __name__ == "__main__":
    main()

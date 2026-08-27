#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Library of Congress fetcher.

The LoC exposes a real JSON API (append fo=json to any search URL) over a
collection of historical film, photographs and recordings that is largely
public domain. Found by surveying sources from a runner: the landing page is
reachable and the API returns real data, unlike Pexels or Musopen which refuse
datacentre traffic outright.
"""
import argparse, json, os, re, subprocess, sys, time
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) loc-fetch/1.0 (educational archive use)"
BASE = "https://www.loc.gov"
VIDEO_EXT = (".mp4", ".mov", ".m4v", ".mpg", ".mpeg", ".avi", ".webm")


def get(url, timeout=60, tries=3):
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            if a == tries - 1:
                raise
            print("   retry (%s)" % str(e)[:50], flush=True)
            time.sleep(3 * (a + 1))


def search(query, count, kind="film-and-videos"):
    url = ("%s/%s/?q=%s&fo=json&c=%d&at=results"
           % (BASE, kind, urllib.parse.quote(query), min(count * 2, 100)))
    d = json.loads(get(url))
    res = d.get("results", [])
    print("LoC %r -> %d results" % (query, len(res)), flush=True)
    return res


def pick_media(item):
    """Walk the resources structure and pull any direct media URL."""
    urls = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, str) and v.lower().split("?")[0].endswith(VIDEO_EXT):
                    urls.append(v if v.startswith("http") else "https:" + v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(item)
    # prefer the largest-looking variant
    def score(u):
        m = re.search(r"(\d{3,4})p?\.", u)
        return int(m.group(1)) if m else 0
    return sorted(set(urls), key=score, reverse=True)


def safe(s, n=60):
    return (re.sub(r"[^\w .\-()]+", "_", str(s)).strip()[:n] or "item")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", required=True, help="comma separated")
    ap.add_argument("--per", type=int, default=15)
    ap.add_argument("--kind", default="film-and-videos")
    ap.add_argument("--max-mb", type=float, default=250.0)
    ap.add_argument("--out", default="out")
    a = ap.parse_args()

    manifest = []
    for q in [x.strip() for x in a.queries.split(",") if x.strip()]:
        d = os.path.join(a.out, safe(q).replace(" ", "_"))
        os.makedirs(d, exist_ok=True)
        got = 0
        try:
            results = search(q, a.per, a.kind)
        except Exception as e:
            print("  search failed: %s" % str(e)[:70], flush=True)
            continue
        for item in results:
            if got >= a.per:
                break
            urls = pick_media(item)
            if not urls:
                continue
            u = urls[0]
            title = item.get("title") or item.get("id") or "loc"
            dst = os.path.join(d, "%02d_%s%s"
                               % (got + 1, safe(title),
                                  os.path.splitext(u.split("?")[0])[1] or ".mp4"))
            head = subprocess.run(["curl", "-sIL", "-m", "25", "-A", UA, u],
                                  capture_output=True, text=True).stdout
            m = re.findall(r"[Cc]ontent-[Ll]ength:\s*(\d+)", head)
            if m and int(m[-1]) > a.max_mb * 2 ** 20:
                print("  skip (too big) %s" % safe(title)[:40], flush=True)
                continue
            r = subprocess.run(["curl", "-sL", "--fail", "-m", "900", "-A", UA, u, "-o", dst])
            if r.returncode != 0 or not os.path.exists(dst) or os.path.getsize(dst) < 50000:
                if os.path.exists(dst):
                    os.remove(dst)
                continue
            got += 1
            manifest.append(dict(query=q, title=title, file=os.path.relpath(dst, a.out),
                                 url=u, page=item.get("url"),
                                 rights=item.get("rights") or item.get("rights_advisory")))
            print("  [%2d/%d] %-46s %6.1f MB"
                  % (got, a.per, str(title)[:46], os.path.getsize(dst) / 2 ** 20), flush=True)
            time.sleep(0.6)
        print("  %r done: %d files" % (q, got), flush=True)

    os.makedirs(a.out, exist_ok=True)
    json.dump(manifest, open(os.path.join(a.out, "MANIFEST.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("DONE: %d files" % len(manifest), flush=True)
    if not manifest:
        sys.exit("nothing downloaded")


if __name__ == "__main__":
    main()

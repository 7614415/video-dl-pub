#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch royalty-free / public-domain media from sources that are unreachable
from the operator's local network, and stage them for artifact upload.

Runs on a GitHub-hosted runner. No credentials required, nothing is pushed
anywhere - the workflow uploads ./out as an artifact.

Sources:
  archive   - archive.org advancedsearch API (public domain, huge)
  mixkit    - mixkit.co free sound effects / video
  urls      - a newline-separated list of direct URLs

Usage:
  python stock_fetch.py --source archive --query "holocaust" --count 25 \
                        --mediatype movies --out out/
"""
import argparse, json, os, re, subprocess, sys, time
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 stock-fetch/1.0"
MAX_MB = 250


def get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def safe(s, n=70):
    s = re.sub(r"[^\w֐-׿ .\-()]+", "_", str(s)).strip()
    return (s[:n] or "item")


def curl(url, dst, referer=None, tries=3):
    for a in range(tries):
        cmd = ["curl", "-sL", "--fail", "-m", "900", "-A", UA]
        if referer:
            cmd += ["-H", "Referer: " + referer]
        cmd += [url, "-o", dst]
        if subprocess.run(cmd).returncode == 0 and os.path.exists(dst) \
                and os.path.getsize(dst) > 20000:
            return True
        time.sleep(2 + a * 3)
    if os.path.exists(dst):
        os.remove(dst)
    return False


# ---------------------------------------------------------------- archive.org
def archive(query, count, mediatype, out):
    """archive.org advancedsearch -> pick playable files per item."""
    q = "%s AND mediatype:(%s)" % (query, mediatype)
    url = ("https://archive.org/advancedsearch.php?q=%s"
           "&fl%%5B%%5D=identifier&fl%%5B%%5D=title&fl%%5B%%5D=year"
           "&fl%%5B%%5D=licenseurl&rows=%d&page=1&output=json"
           % (urllib.parse.quote(q), max(count * 3, 30)))
    data = json.loads(get(url))
    docs = data.get("response", {}).get("docs", [])
    print("archive.org: %d candidate items for %r" % (len(docs), query), flush=True)

    want_v = (".mp4", ".m4v", ".webm", ".ogv")
    want_a = (".mp3", ".ogg", ".flac", ".wav")
    exts = want_v if mediatype == "movies" else want_a
    got, manifest = 0, []
    for doc in docs:
        if got >= count:
            break
        ident = doc.get("identifier")
        try:
            meta = json.loads(get("https://archive.org/metadata/%s" % ident, timeout=40))
        except Exception as e:
            print("  meta fail %s: %s" % (ident, str(e)[:60]), flush=True)
            continue
        files = meta.get("files", [])
        cands = []
        for f in files:
            nm = f.get("name", "")
            if not nm.lower().endswith(exts):
                continue
            try:
                sz = int(f.get("size", 0))
            except Exception:
                sz = 0
            if 0 < sz <= MAX_MB * 2 ** 20:
                cands.append((sz, nm))
        if not cands:
            continue
        cands.sort(reverse=True)          # largest that still fits = best quality
        sz, nm = cands[0]
        ext = os.path.splitext(nm)[1]
        dst = os.path.join(out, "%02d_%s%s" % (got + 1, safe(doc.get("title") or ident), ext))
        src = "https://archive.org/download/%s/%s" % (ident, urllib.parse.quote(nm))
        print("  [%d/%d] %s (%.1f MB)" % (got + 1, count, ident, sz / 2 ** 20), flush=True)
        if curl(src, dst):
            got += 1
            manifest.append(dict(identifier=ident, title=doc.get("title"),
                                 year=doc.get("year"), license=doc.get("licenseurl"),
                                 file=os.path.basename(dst), source=src,
                                 page="https://archive.org/details/%s" % ident))
    return manifest


# ------------------------------------------------------------------- mixkit
def mixkit(query, count, kind, out):
    base = "https://mixkit.co/free-%s/%s/" % (
        "sound-effects" if kind == "audio" else "stock-video", urllib.parse.quote(query))
    try:
        html = get(base).decode("utf-8", "ignore")
    except Exception as e:
        print("mixkit fetch failed:", str(e)[:80], flush=True)
        return []
    pat = r'https://assets\.mixkit\.co/[^"\'\s]+\.(?:mp3|wav|mp4)'
    urls = []
    for u in re.findall(pat, html):
        if u not in urls:
            urls.append(u)
    print("mixkit: %d direct urls" % len(urls), flush=True)
    manifest = []
    for i, u in enumerate(urls[:count], 1):
        dst = os.path.join(out, "%02d_%s" % (i, safe(os.path.basename(u))))
        if curl(u, dst, referer="https://mixkit.co/"):
            manifest.append(dict(file=os.path.basename(dst), source=u))
    return manifest


# --------------------------------------------------------------------- urls
def urls_list(blob, out):
    manifest = []
    items = [u.strip() for u in blob.splitlines() if u.strip().startswith("http")]
    print("url list: %d entries" % len(items), flush=True)
    for i, u in enumerate(items, 1):
        dst = os.path.join(out, "%02d_%s" % (i, safe(os.path.basename(urllib.parse.urlparse(u).path))))
        if curl(u, dst):
            manifest.append(dict(file=os.path.basename(dst), source=u))
    return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, choices=["archive", "mixkit", "urls"])
    ap.add_argument("--query", default="")
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--mediatype", default="movies", help="archive: movies|audio")
    ap.add_argument("--kind", default="audio", help="mixkit: audio|video")
    ap.add_argument("--urls", default="")
    ap.add_argument("--out", default="out")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    if a.source == "archive":
        man = archive(a.query, a.count, a.mediatype, a.out)
    elif a.source == "mixkit":
        man = mixkit(a.query, a.count, a.kind, a.out)
    else:
        man = urls_list(a.urls, a.out)

    json.dump(man, open(os.path.join(a.out, "MANIFEST.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    total = sum(os.path.getsize(os.path.join(a.out, f)) for f in os.listdir(a.out))
    print("DONE: %d files, %.1f MB" % (len(man), total / 2 ** 20), flush=True)
    if not man:
        sys.exit("nothing downloaded")


if __name__ == "__main__":
    main()

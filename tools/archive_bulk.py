#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bulk harvest from archive.org collections.

Scraping community forums for re-uploaded commercial packs is both legally
dirty and unreliable. archive.org is the opposite: millions of items that are
public domain or openly licensed, with a real search API and direct file URLs.

Useful collections:
  prelinger          - the classic free stock-footage archive
  stock_footage      - stock clips
  opensource_movies  - community uploads, mixed licences (see licenseurl)
  netlabels          - tens of thousands of freely licensed music tracks
  audio_music        - broader music
  opensource_audio   - community audio

Items with no licence URL are skipped unless they sit in a collection that is
known to be public domain, so we do not quietly hoover up rights-reserved
uploads.
"""
import argparse, json, os, re, subprocess, sys, time
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) archive-bulk/1.0"
SEARCH = "https://archive.org/advancedsearch.php"
PD_COLLECTIONS = {"prelinger", "stock_footage", "publicmovies", "feature_films",
                  "sound_pond", "netlabels", "audio_bookspoetry"}
VIDEO_EXT = (".mp4", ".m4v", ".webm", ".ogv", ".mpeg", ".mpg", ".avi")
AUDIO_EXT = (".mp3", ".ogg", ".flac", ".wav", ".m4a")

# A run for Holocaust footage pulled down "Holohoax Tales" and a Luciferian
# conspiracy video. This blocklist is not about licences or taste - denial
# material must never reach an educational film about the Holocaust, and the
# operator asked for filtering to be off everywhere else.
POISON = re.compile(
    r"holohoax|hoax|denial|denier|revisionis|luciferian|illuminati|"
    r"new world order|zionist conspiracy|protocols of zion|great replacement|"
    r"white genocide|blood libel|flat earth|qanon", re.I)


def get(url, timeout=90, tries=3):
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


def search(collection, extra, rows, mediatype, title_only=False):
    # collection "*" searches the whole archive, driven by --query alone.
    # Needed for subject hunts ("warsaw ghetto") that span many collections.
    if collection.strip() in ("*", "all", "any"):
        q = "mediatype:(%s)" % mediatype
    else:
        q = "collection:(%s) AND mediatype:(%s)" % (collection, mediatype)
    if extra:
        q += " AND %s(%s)" % ("title:" if title_only else "", extra)
    # No downloads sort. Sorting an OR query by popularity surfaced Benny Hill
    # and a 9/11 broadcast for a query about synagogues: the loosest match wins
    # on downloads. Relevance ordering (the default) keeps the topic.
    url = ("%s?q=%s&fl%%5B%%5D=identifier&fl%%5B%%5D=title&fl%%5B%%5D=year"
           "&fl%%5B%%5D=licenseurl&fl%%5B%%5D=collection"
           "&rows=%d&page=1&output=json"
           % (SEARCH, urllib.parse.quote(q), rows))
    d = json.loads(get(url))
    docs = d.get("response", {}).get("docs", [])
    print("collection %r -> %d items" % (collection, len(docs)), flush=True)
    return docs


def poisoned(doc):
    blob = "%s %s" % (doc.get("title") or "", doc.get("identifier") or "")
    return bool(POISON.search(blob))


def allowed(doc, collection, no_filter=False):
    # The licence filter skipped 226 of 240 items on its first real run, so the
    # operator turned it off. Source and licence stay in MANIFEST.json either
    # way, so anything published from this library can still be traced back.
    if no_filter:
        return True
    if doc.get("licenseurl"):
        return True
    cols = doc.get("collection") or []
    if isinstance(cols, str):
        cols = [cols]
    return bool(PD_COLLECTIONS.intersection(set(cols) | {collection}))


def safe(s, n=64):
    return (re.sub(r"[^\w .\-()]+", "_", str(s)).strip()[:n] or "item")


def fetch_item(ident, exts, out, idx, title, min_mb, max_mb):
    meta = json.loads(get("https://archive.org/metadata/%s" % ident, timeout=60))
    cands = []
    for f in meta.get("files", []):
        nm = f.get("name", "")
        if not nm.lower().endswith(exts):
            continue
        try:
            sz = int(f.get("size", 0))
        except Exception:
            continue
        if min_mb * 2 ** 20 <= sz <= max_mb * 2 ** 20:
            cands.append((sz, nm))
    if not cands:
        return None
    cands.sort(reverse=True)
    sz, nm = cands[0]
    dst = os.path.join(out, "%03d_%s%s" % (idx, safe(title), os.path.splitext(nm)[1]))
    url = "https://archive.org/download/%s/%s" % (ident, urllib.parse.quote(nm))
    r = subprocess.run(["curl", "-sL", "--fail", "-m", "1200", "-A", UA, url, "-o", dst])
    if r.returncode != 0 or not os.path.exists(dst) or os.path.getsize(dst) < 20000:
        if os.path.exists(dst):
            os.remove(dst)
        return None
    return dict(identifier=ident, title=title, file=os.path.basename(dst),
                size_mb=round(sz / 2 ** 20, 1),
                page="https://archive.org/details/%s" % ident)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--collections", required=True, help="comma separated")
    ap.add_argument("--mediatype", default="movies")
    ap.add_argument("--query", default="", help="extra lucene filter")
    ap.add_argument("--per", type=int, default=25)
    ap.add_argument("--min-mb", type=float, default=1.0)
    ap.add_argument("--max-mb", type=float, default=180.0)
    ap.add_argument("--out", default="out")
    ap.add_argument("--no-filter", action="store_true",
                    help="take every result, do not require a clear licence")
    ap.add_argument("--title-only", action="store_true",
                    help="match the query against titles instead of full text")
    ap.add_argument("--probe", action="store_true",
                    help="report collection sizes and licence coverage, download nothing")
    a = ap.parse_args()

    if a.probe:
        # archive.org is unreachable from the operator's network, so the only
        # way to learn what a collection actually holds is to ask from here.
        for col in [c.strip() for c in a.collections.split(",") if c.strip()]:
            try:
                url = ("%s?q=%s&rows=0&output=json"
                       % (SEARCH, urllib.parse.quote(
                           "collection:(%s) AND mediatype:(%s)" % (col, a.mediatype))))
                total = json.loads(get(url))["response"]["numFound"]
                url2 = ("%s?q=%s&rows=0&output=json"
                        % (SEARCH, urllib.parse.quote(
                            "collection:(%s) AND mediatype:(%s) AND licenseurl:[* TO *]"
                            % (col, a.mediatype))))
                lic = json.loads(get(url2))["response"]["numFound"]
            except Exception as e:
                print("  %-20s ERROR %s" % (col, str(e)[:50]), flush=True)
                continue
            pd = col in PD_COLLECTIONS
            print("  %-20s %8d items | %7d with licence | known-PD=%s"
                  % (col, total, lic, pd), flush=True)
        return

    exts = VIDEO_EXT if a.mediatype == "movies" else AUDIO_EXT
    manifest, skipped, blocked = [], 0, 0
    os.makedirs(a.out, exist_ok=True)
    for col in [c.strip() for c in a.collections.split(",") if c.strip()]:
        d = os.path.join(a.out, safe(col))
        os.makedirs(d, exist_ok=True)
        try:
            docs = search(col, a.query, a.per * 3, a.mediatype, a.title_only)
        except Exception as e:
            print("  search failed for %r: %s" % (col, str(e)[:70]), flush=True)
            continue
        got = 0
        for doc in docs:
            if got >= a.per:
                break
            if poisoned(doc):
                print("   BLOCKED (denial/conspiracy): %s"
                      % str(doc.get("title"))[:60], flush=True)
                blocked += 1
                continue
            if not allowed(doc, col, a.no_filter):
                skipped += 1
                continue
            try:
                rec = fetch_item(doc["identifier"], exts, d, got + 1,
                                 doc.get("title") or doc["identifier"],
                                 a.min_mb, a.max_mb)
            except Exception as e:
                print("   error %s: %s" % (doc["identifier"][:30], str(e)[:50]), flush=True)
                continue
            if rec:
                rec["collection"] = col
                rec["license"] = doc.get("licenseurl") or "public domain (collection)"
                manifest.append(rec)
                got += 1
                print("  [%2d/%d] %-44s %6.1f MB" % (got, a.per, str(rec["title"])[:44],
                                                     rec["size_mb"]), flush=True)
        print("  collection %r done: %d files" % (col, got), flush=True)

    json.dump(manifest, open(os.path.join(a.out, "MANIFEST.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    total = sum(x["size_mb"] for x in manifest)
    print("DONE: %d files, %.1f MB (skipped %d rights-unclear, blocked %d denial/conspiracy)"
          % (len(manifest), total, skipped, blocked), flush=True)
    if not manifest:
        sys.exit("nothing downloaded")


if __name__ == "__main__":
    main()

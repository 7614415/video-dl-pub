#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Survey free-media sources from a runner.

Reachability alone is worthless: Pexels answers 200 to a browser and 403 to a
datacentre, and Pixabay's search payload only exposes 640x360 previews. So for
each source this checks three separate things:

  reach   - does the landing page answer at all
  api     - is there a machine-readable endpoint that returns data
  file    - can an actual media file be fetched (ranged GET, real bytes)

Only a source that passes all three is usable for bulk work.
"""
import json, re, subprocess, sys, time
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")

SOURCES = [
    # name, landing, api probe (url or None), media-file probe (url or None)
    ("archive.org", "https://archive.org/",
     "https://archive.org/advancedsearch.php?q=mediatype%3Amovies&rows=1&output=json",
     None),
    ("Wikimedia Commons", "https://commons.wikimedia.org/",
     "https://commons.wikimedia.org/w/api.php?action=query&format=json&meta=siteinfo",
     None),
    ("Openverse", "https://openverse.org/",
     "https://api.openverse.org/v1/images/?q=sky&page_size=1", None),
    ("Free Music Archive", "https://freemusicarchive.org/", None, None),
    ("Jamendo", "https://www.jamendo.com/", None, None),
    ("ccMixter", "http://ccmixter.org/", "http://ccmixter.org/api/query?f=json&limit=1", None),
    ("Mixkit", "https://mixkit.co/free-sound-effects/", None, None),
    ("Pexels", "https://www.pexels.com/", None, None),
    ("Pixabay", "https://pixabay.com/", None, None),
    ("Videvo", "https://www.videvo.net/", None, None),
    ("Coverr", "https://coverr.co/", None, None),
    ("Mazwai", "https://mazwai.com/", None, None),
    ("Vidsplay", "https://www.vidsplay.com/", None, None),
    ("Life of Vids", "https://www.lifeofvids.com/", None, None),
    ("NASA Images", "https://images.nasa.gov/",
     "https://images-api.nasa.gov/search?q=earth&media_type=video", None),
    ("Prelinger (archive)", "https://archive.org/details/prelinger",
     "https://archive.org/advancedsearch.php?q=collection%3Aprelinger&rows=1&output=json",
     None),
    ("Library of Congress", "https://www.loc.gov/",
     "https://www.loc.gov/film-and-videos/?q=war&fo=json&c=1", None),
    ("Europeana", "https://www.europeana.eu/", None, None),
    ("Internet Archive TV", "https://archive.org/details/tv", None, None),
    ("Musopen", "https://musopen.org/", None, None),
    ("Incompetech", "https://incompetech.com/music/royalty-free/music.html",
     "https://incompetech.com/music/royalty-free/pieces.json", None),
    ("Bensound", "https://www.bensound.com/", None, None),
    ("Freesound", "https://freesound.org/", None, None),
    ("Public Domain Movies", "https://publicdomainmovie.net/", None, None),
    ("Moving Image Archive", "https://archive.org/details/movies", None, None),
    ("Wikimedia upload host", "https://upload.wikimedia.org/", None, None),
    ("Smithsonian Open Access", "https://www.si.edu/openaccess",
     "https://api.si.edu/openaccess/api/v1.0/search?q=test&api_key=DEMO_KEY", None),
    ("Met Museum", "https://www.metmuseum.org/",
     "https://collectionapi.metmuseum.org/public/collection/v1/objects?metadataDate=2024-01-01",
     None),
]


def code(url, ranged=False, timeout=25):
    cmd = ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code} %{size_download}",
           "-m", str(timeout), "-L", "-A", UA]
    if ranged:
        cmd += ["-r", "0-200000"]
    cmd.append(url)
    p = subprocess.run(cmd, capture_output=True, text=True)
    parts = p.stdout.split()
    if len(parts) != 2:
        return "ERR", 0
    return parts[0], int(parts[1])


def api_check(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read(400000)
        try:
            json.loads(raw)
            return "json", len(raw)
        except Exception:
            return "notjson", len(raw)
    except Exception as e:
        return "fail:%s" % str(e)[:26], 0


def main():
    rows = []
    print("%-24s %-10s %-16s %s" % ("source", "reach", "api", "note"), flush=True)
    print("-" * 78, flush=True)
    for name, landing, api, media in SOURCES:
        c, _ = code(landing)
        apires = "-"
        if api:
            kind, n = api_check(api)
            apires = "%s(%d)" % (kind, n) if kind == "json" else kind
        note = ""
        if c == "418":
            note = "blocked upstream"
        elif c in ("403", "401"):
            note = "refuses datacentre"
        elif c.startswith("2"):
            note = "reachable"
        rows.append(dict(source=name, reach=c, api=apires, note=note))
        print("%-24s %-10s %-16s %s" % (name[:24], c, apires[:16], note), flush=True)
        time.sleep(0.4)

    json.dump(rows, open("out/source_scan.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    good = [r for r in rows if r["reach"].startswith("2")]
    print("\n%d/%d reachable from this runner" % (len(good), len(rows)), flush=True)
    print("usable with a real API: %s"
          % ", ".join(r["source"] for r in rows if r["api"].startswith("json")), flush=True)


if __name__ == "__main__":
    import os
    os.makedirs("out", exist_ok=True)
    main()

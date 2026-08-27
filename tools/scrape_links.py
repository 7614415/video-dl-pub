#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch pages that the operator's network refuses, and extract the download
links they contain. Produces a small JSON/markdown report, not the media -
the report downloads in seconds, then we decide what is worth pulling.

Nothing is downloaded from the extracted links here. That is deliberate:
community forums mix genuinely free material with re-uploaded commercial
packs, and the decision of what to take belongs to a human.
"""
import argparse, html, json, os, re, sys, time
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
HDRS = {"User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7"}

HOSTS = {
    "drive.google.com": "Google Drive",
    "docs.google.com": "Google Docs",
    "mega.nz": "MEGA",
    "mega.co.nz": "MEGA",
    "mediafire.com": "MediaFire",
    "dropbox.com": "Dropbox",
    "wetransfer.com": "WeTransfer",
    "we.tl": "WeTransfer",
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "vimeo.com": "Vimeo",
    "pixabay.com": "Pixabay",
    "pexels.com": "Pexels",
    "mixkit.co": "Mixkit",
    "videvo.net": "Videvo",
    "archive.org": "archive.org",
    "1drv.ms": "OneDrive",
    "onedrive.live.com": "OneDrive",
}
DIRECT = re.compile(r"\.(mp4|mov|mp3|wav|zip|rar|7z|aep|prproj|mogrt)(\?|$)", re.I)
HREF = re.compile(r'href=["\']([^"\']+)["\']', re.I)
TITLE = re.compile(r"<title>(.*?)</title>", re.I | re.S)


def get(url, timeout=60):
    req = urllib.request.Request(url, headers=HDRS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    for enc in ("utf-8", "windows-1255", "iso-8859-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")


def classify(u):
    host = urllib.parse.urlparse(u).netloc.lower().replace("www.", "")
    for k, v in HOSTS.items():
        if host.endswith(k):
            return v
    if DIRECT.search(u):
        return "direct file"
    return None


def diagnose(page):
    """Why a page yields nothing is usually not 'no links' but 'not logged in'."""
    low = page.lower()
    marks = {
        "login_wall": any(k in low for k in (
            "must be registered", "log in or register", "להתחבר", "הרשמה",
            "you must be logged in", 'name="login"')),
        "xenforo": "xenforo" in low,
        "cloudflare": "cf-browser-verification" in low or "just a moment" in low,
        "post_bodies": low.count("bbwrapper") + low.count("message-body"),
        "spoilers": low.count("bbcodespoiler") + low.count("bbcodeblock"),
        "chars": len(page),
        "all_href": low.count("href="),
    }
    return marks


def scrape(url):
    page = get(url)
    title = html.unescape(TITLE.search(page).group(1).strip()) if TITLE.search(page) else ""
    seen, out = set(), []
    for raw in HREF.findall(page):
        u = html.unescape(raw)
        if u.startswith("/"):
            u = urllib.parse.urljoin(url, u)
        if not u.startswith("http"):
            continue
        kind = classify(u)
        if not kind:
            continue
        if u in seen:
            continue
        seen.add(u)
        out.append(dict(kind=kind, url=u))
    return title, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--urls", required=True, help="newline or comma separated")
    ap.add_argument("--out", default="out")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    targets = [u.strip() for u in re.split(r"[\n,]+", a.urls) if u.strip().startswith("http")]
    report, md = [], ["# Extracted links", ""]
    for u in targets:
        try:
            title, links = scrape(u)
        except Exception as e:
            print("FAILED %s -> %s" % (u[:70], str(e)[:70]), flush=True)
            md += ["## FAILED: %s" % u, "`%s`" % str(e)[:120], ""]
            continue
        diag = diagnose(get(u))
        print("%-52s %d links | %s" % (title[:52], len(links), diag), flush=True)
        report.append(dict(page=u, title=title, links=links, diagnostics=diag))
        md += ["## %s" % title, "<%s>" % u, ""]
        by = {}
        for l in links:
            by.setdefault(l["kind"], []).append(l["url"])
        for kind in sorted(by):
            md.append("### %s (%d)" % (kind, len(by[kind])))
            md += ["- %s" % x for x in by[kind][:60]]
            md.append("")
        time.sleep(1.5)

    json.dump(report, open(os.path.join(a.out, "links.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    open(os.path.join(a.out, "links.md"), "w", encoding="utf-8").write("\n".join(md))
    total = sum(len(r["links"]) for r in report)
    print("DONE: %d pages, %d links" % (len(report), total), flush=True)
    if not report:
        sys.exit("no page could be read")


if __name__ == "__main__":
    main()

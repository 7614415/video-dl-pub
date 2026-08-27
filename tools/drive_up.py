#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Upload a local folder to Google Drive using the repo's OAuth secrets.

Exists so that multi-gigabyte hauls never travel through the operator's
network, which scans every download and caps it near 120 KB/s. The runner
pulls from the source and pushes to Drive; the operator then has it at
Google speed.

env: CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN
"""
import json, mimetypes, os, sys, time
import urllib.parse
import urllib.request

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&supportsAllDrives=true"
FILES = "https://www.googleapis.com/drive/v3/files"
CHUNK = 8 * 1024 * 1024


def access_token():
    body = urllib.parse.urlencode({
        "client_id": os.environ["CLIENT_ID"],
        "client_secret": os.environ["CLIENT_SECRET"],
        "refresh_token": os.environ["REFRESH_TOKEN"],
        "grant_type": "refresh_token"}).encode()
    req = urllib.request.Request(TOKEN_URL, data=body,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["access_token"]


def api(tok, url, method="GET", data=None, headers=None):
    h = {"Authorization": "Bearer " + tok}
    if data is not None:
        h["Content-Type"] = "application/json; charset=UTF-8"
        data = json.dumps(data).encode()
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def ensure_folder(tok, name, parent=None):
    q = ("mimeType='application/vnd.google-apps.folder' and trashed=false and name='%s'"
         % name.replace("'", "\\'"))
    if parent:
        q += " and '%s' in parents" % parent
    url = FILES + "?q=" + urllib.parse.quote(q) + "&fields=files(id,name)&pageSize=5"
    hit = api(tok, url).get("files", [])
    if hit:
        return hit[0]["id"]
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent:
        meta["parents"] = [parent]
    return api(tok, FILES + "?fields=id", "POST", meta)["id"]


def upload(tok, path, parent):
    name = os.path.basename(path)
    size = os.path.getsize(path)
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    req = urllib.request.Request(
        UPLOAD, data=json.dumps({"name": name, "parents": [parent]}).encode(),
        headers={"Authorization": "Bearer " + tok,
                 "Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Type": mime,
                 "X-Upload-Content-Length": str(size)}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        session = r.headers["Location"]

    sent = 0
    with open(path, "rb") as f:
        while sent < size:
            block = f.read(CHUNK)
            end = sent + len(block) - 1
            put = urllib.request.Request(
                session, data=block, method="PUT",
                headers={"Content-Length": str(len(block)),
                         "Content-Range": "bytes %d-%d/%d" % (sent, end, size)})
            for attempt in range(4):
                try:
                    with urllib.request.urlopen(put, timeout=600) as r:
                        r.read()
                    break
                except urllib.error.HTTPError as e:
                    if e.code in (308,):          # resume incomplete = fine
                        break
                    if e.code in (500, 502, 503, 504) and attempt < 3:
                        time.sleep(2 ** attempt)
                        continue
                    raise
            sent = end + 1
    return name, size


def main():
    src = sys.argv[1]
    root_name = sys.argv[2] if len(sys.argv) > 2 else "stock-assets"
    tok = access_token()
    root = ensure_folder(tok, root_name)
    print("drive folder %r -> %s" % (root_name, root), flush=True)

    total, count = 0, 0
    for dirpath, _dirs, files in os.walk(src):
        rel = os.path.relpath(dirpath, src)
        parent = root
        if rel not in (".", ""):
            for part in rel.replace("\\", "/").split("/"):
                parent = ensure_folder(tok, part, parent)
        for fn in sorted(files):
            p = os.path.join(dirpath, fn)
            try:
                name, size = upload(tok, p, parent)
            except Exception as e:
                print("  FAIL %-40s %s" % (fn[:40], str(e)[:60]), flush=True)
                continue
            total += size
            count += 1
            print("  up %-46s %7.1f MB" % (name[:46], size / 2 ** 20), flush=True)
    print("UPLOADED %d files, %.1f MB -> Drive/%s" % (count, total / 2 ** 20, root_name),
          flush=True)
    if count == 0:
        sys.exit("nothing uploaded")


if __name__ == "__main__":
    main()

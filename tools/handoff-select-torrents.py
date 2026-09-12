#!/usr/bin/env python3
"""Resolve one qBittorrent selection to all linked UA tracker torrents."""
import http.cookiejar
import importlib.util
import json
import os
import stat
import sys
import base64
import urllib.parse
import urllib.request

ROOT = "/mnt/nvme11n1/artemisprime"
CONFIG = ROOT + "/Upload-Assistant-wastaken/docker-data/data/config.py"


def identity(path):
    """Return a stable hardlink identity for a file or complete directory.

    Tracker trees for directory torrents have distinct directory inodes, so a
    directory's inode cannot identify the shared payload.  Compare the sorted
    identities of every regular file instead.  This is manual-only work and is
    cached below, so it is preferable to silently omitting a valid release.
    """
    try:
        details = os.stat(path)
    except OSError:
        return ""
    if stat.S_ISREG(details.st_mode):
        return ("file", details.st_dev, details.st_ino, details.st_size, details.st_mtime_ns)
    if not stat.S_ISDIR(details.st_mode):
        return ""
    members = []
    for root, _, names in os.walk(path):
        for name in names:
            candidate = os.path.join(root, name)
            try:
                member = os.stat(candidate)
            except OSError:
                continue
            if stat.S_ISREG(member.st_mode):
                members.append((member.st_dev, member.st_ino, member.st_size, member.st_mtime_ns))
    return ("directory", tuple(sorted(members))) if members else ""


if len(sys.argv) == 3 and sys.argv[1] == "--base64":
    try:
        needle = base64.b64decode(sys.argv[2], validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        raise SystemExit("invalid encoded selection")
elif len(sys.argv) == 2:
    needle = sys.argv[1]
else:
    raise SystemExit("usage: handoff-select-torrents.py [--base64] CONTENT_PATH_OR_INFOHASH")
if not needle or "\x00" in needle:
    raise SystemExit("invalid selection")
spec = importlib.util.spec_from_file_location("ua_config", CONFIG)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
client = module.config["TORRENT_CLIENTS"]["qbittorrent"]
base = f"http://127.0.0.1:{client['qbit_port']}"
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def request(path, data=None):
    headers = {"Content-Type": "application/x-www-form-urlencoded"} if data else {}
    return opener.open(urllib.request.Request(base + path, data=data, headers=headers), timeout=30).read()


request("/api/v2/auth/login", urllib.parse.urlencode({"username": client["qbit_user"], "password": client["qbit_pass"]}).encode())
torrents = json.loads(request("/api/v2/torrents/info"))
selected = next((item for item in torrents if item.get("hash", "").casefold() == needle.casefold()), None)
if selected is None:
    selected = next((item for item in torrents if item.get("content_path") == needle), None)
if selected is None:
    raise SystemExit("selected qBittorrent torrent was not found")
if selected.get("progress", 0) < 1 or selected.get("state") in {"missingFiles", "error"}:
    raise SystemExit("select a completed torrent with an existing payload")
identity_cache = {}


def cached_identity(path):
    if path not in identity_cache:
        identity_cache[path] = identity(path)
    return identity_cache[path]


selected_identity = cached_identity(selected.get("content_path", ""))
if not selected_identity:
    raise SystemExit("selected torrent content is missing, empty, or unsupported")
matches = [
    item["hash"] for item in torrents
    if item.get("category") == "Uploads"
    and item.get("progress", 0) >= 1
    and item.get("state") not in {"missingFiles", "error"}
    and cached_identity(item.get("content_path", "")) == selected_identity
]
if not matches:
    raise SystemExit("no completed Uploads tracker hardlinks match the selected torrent")
print(json.dumps({"selected_hash": selected["hash"], "handoff_hashes": sorted(matches)}))

#!/usr/bin/env python3
"""Resolve one completed non-UA qB selection for a manual Grape handoff."""
import base64
import http.cookiejar
import importlib.util
import json
import os
import sys
import urllib.parse
import urllib.request

ROOT = "/mnt/nvme11n1/artemisprime"
CONFIG = ROOT + "/Upload-Assistant-wastaken/docker-data/data/config.py"

if len(sys.argv) == 3 and sys.argv[1] == "--base64":
    needle = base64.b64decode(sys.argv[2], validate=True).decode()
elif len(sys.argv) == 2:
    needle = sys.argv[1]
else:
    raise SystemExit("usage: racing-handoff-select.py [--base64] CONTENT_PATH_OR_INFOHASH")

spec = importlib.util.spec_from_file_location("ua_config", CONFIG)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
client = module.config["TORRENT_CLIENTS"]["qbittorrent"]
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
base = f"http://127.0.0.1:{client['qbit_port']}"
login = urllib.parse.urlencode({"username": client["qbit_user"], "password": client["qbit_pass"]}).encode()
opener.open(urllib.request.Request(base + "/api/v2/auth/login", data=login), timeout=30)
torrents = json.loads(opener.open(base + "/api/v2/torrents/info", timeout=30).read())
item = next((x for x in torrents if x.get("hash", "").casefold() == needle.casefold() or x.get("content_path") == needle), None)
if not item:
    raise SystemExit("selected qBittorrent torrent was not found")
if item.get("category") == "Uploads" or item.get("progress", 0) < 1 or not os.path.exists(item.get("content_path", "")):
    raise SystemExit("select a completed non-Uploads torrent with an existing payload")
print(json.dumps({"hash": item["hash"], "name": item.get("name"), "category": item.get("category", ""), "tags": item.get("tags", "")}))

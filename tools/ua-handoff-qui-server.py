#!/usr/bin/env python3
"""Authenticated, Docker-bridge-only trigger for QUI's manual handoff action."""
import hmac
import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN_FILE = "/home/artemis/.config/upload-assistant/qui-handoff.token"
LAUNCHER = "/home/artemis/.local/bin/ua-handoff-selected"
RACING_LAUNCHER = "/home/artemis/.local/bin/ua-racing-handoff-selected"
LOG_FILE = "/home/artemis/.local/share/ua-handoff-selected.log"


def token():
    with open(TOKEN_FILE, encoding="utf-8") as handle:
        return handle.read().strip()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        launchers = {"/handoff/clementine": LAUNCHER, "/handoff/clementine-racing": RACING_LAUNCHER}
        launcher = launchers.get(self.path)
        if not launcher:
            return self.reply(404, {"error": "not found"})
        if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token()):
            return self.reply(401, {"error": "unauthorized"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= 8192:
                raise ValueError("invalid request length")
            path = json.loads(self.rfile.read(length)).get("path")
            if not isinstance(path, str) or not path or "\x00" in path or len(path) > 4096:
                raise ValueError("invalid content path")
        except (ValueError, json.JSONDecodeError):
            return self.reply(400, {"error": "invalid content path"})
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        log = open(LOG_FILE, "ab", buffering=0)
        subprocess.Popen(["/usr/bin/flock", "-w", "120", "/tmp/ua-clementine-handoff.lock", launcher, path], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        return self.reply(202, {"accepted": True, "message": "manual handoff queued"})


ThreadingHTTPServer(("172.60.0.1", 7478), Handler).serve_forever()

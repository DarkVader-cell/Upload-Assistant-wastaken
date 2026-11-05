"""Persistent, credential-free API pacing shared by catalogue subprocesses."""

from __future__ import annotations

import re
import sqlite3
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit


def ptp_api_redirect(source, location):
    """PTP group or SAME-IMDb search redirect only; never broaden a search."""
    if not location:
        return None
    source, target = urlsplit(str(source)), urlsplit(urljoin(str(source), str(location)))
    if (
        source.scheme != "https"
        or source.hostname != "passthepopcorn.me"
        or source.path != "/torrents.php"
        or target.scheme != "https"
        or target.hostname != source.hostname
        or target.path != "/torrents.php"
        or source.username
        or source.password
        or target.username
        or target.password
        or target.fragment
    ):
        return None
    try:
        if source.port not in (None, 443) or target.port not in (None, 443):
            return None
    except ValueError:
        return None
    query = parse_qs(target.query, keep_blank_values=True)
    if "json" in query and query["json"] not in (["1"], ["noredirect"]):
        return None
    if set(query) <= {"id", "json"} and len(query.get("id", [])) == 1 and re.fullmatch(r"[1-9][0-9]{0,11}", query["id"][0]):
        parameters = {"id": query["id"][0], "json": "1"}
    elif set(query) <= {"searchstr", "json"}:
        original = parse_qs(source.query, keep_blank_values=True).get("imdb", [])
        if len(original) != 1 or not re.fullmatch(r"(?:tt)?[0-9]{7,10}", original[0]):
            return None
        expected = "tt" + original[0].removeprefix("tt")
        if query.get("searchstr") != [expected]:
            return None
        parameters = {"searchstr": expected, "json": "1"}
    else:
        return None
    return "https://passthepopcorn.me/torrents.php?" + urlencode(parameters)


class RateLimitError(RuntimeError):
    """A safe-to-display local API budget/cooldown guard."""


def retry_delay(headers, now):
    value = headers.get("retry-after", "")
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        try:
            return max(0.0, parsedate_to_datetime(value).timestamp() - now)
        except (TypeError, ValueError, OverflowError):
            return 0.0


class APIPacer:
    """Never automatically retries a request; exhausted budgets fail closed."""

    def __init__(self, path: Path, interval=10, daily_limit=200, clock=time.time, sleeper=time.sleep):
        self.path = Path(path)
        self.interval = max(2.0, float(interval))
        self.daily_limit = max(1, int(daily_limit))
        self.clock, self.sleep = clock, sleeper
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._connect().close()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS hosts(host TEXT PRIMARY KEY,day TEXT NOT NULL,requests INTEGER NOT NULL DEFAULT 0,next_at REAL NOT NULL DEFAULT 0,cooldown REAL NOT NULL DEFAULT 0,failures INTEGER NOT NULL DEFAULT 0)"
        )
        connection.commit()
        self.path.chmod(0o600)
        return connection

    def acquire(self, host):
        while True:
            now = self.clock()
            day = datetime.fromtimestamp(now, UTC).date().isoformat()
            db = self._connect()
            try:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT day,requests,next_at,cooldown FROM hosts WHERE host=?", (host,)).fetchone()
                requests = row[1] if row and row[0] == day else 0
                if requests >= self.daily_limit:
                    raise RateLimitError(f"{host}: catalogue daily API budget reached; no request sent")
                if row and row[3] > now:
                    raise RateLimitError(f"{host}: API cooldown active; no request sent")
                wait = max(0.0, row[2] - now) if row else 0.0
                if not wait:
                    db.execute(
                        "INSERT INTO hosts(host,day,requests,next_at) VALUES(?,?,?,?) ON CONFLICT(host) DO UPDATE SET day=excluded.day,requests=excluded.requests,next_at=excluded.next_at",
                        (host, day, requests + 1, now + self.interval),
                    )
                    db.commit()
                    return
                db.rollback()
            finally:
                db.close()
            self.sleep(wait)

    def record_response(self, host, response):
        status = response.status_code
        if status == 200:
            try:
                data = response.json()
                if isinstance(data, dict):
                    failed = data.get("success") is False or bool(data.get("error") or data.get("errors")) or data.get("status") not in (None, 0, 200, "success")
                    messages = " ".join(str(data.get(key, "")) for key in ("message", "error", "errors"))
                    if failed and re.search(r"\brate[\s_-]*limit|\btoo many requests", messages, re.IGNORECASE):
                        status = 429
            except ValueError:
                pass
        self.record(host, status, response.headers)
        return status

    def record(self, host, status, headers):
        now = self.clock()
        normalized = {str(key).lower(): str(value) for key, value in headers.items()}
        delay = retry_delay(normalized, now)
        db = self._connect()
        try:
            with db:
                row = db.execute("SELECT failures FROM hosts WHERE host=?", (host,)).fetchone()
                failures = (row[0] if row else 0) + 1 if status in {429, 503} else 0
                if status in {429, 503}:
                    delay = max(delay, min(21600, 60 * 2 ** min(failures - 1, 9)))
                remaining = normalized.get("x-ratelimit-remaining", normalized.get("ratelimit-remaining"))
                if remaining == "0":
                    reset = normalized.get("x-ratelimit-reset", normalized.get("ratelimit-reset", ""))
                    try:
                        value = float(reset)
                        if "x-ratelimit-reset" in normalized:
                            value = value / 1000 if value > 100000000000 else value
                            value = value - now
                        delay = max(delay, value, 60)
                    except ValueError:
                        delay = max(delay, 60)
                db.execute(
                    "UPDATE hosts SET next_at=max(next_at,?),cooldown=max(cooldown,?),failures=? WHERE host=?",
                    (now + self.interval, now + delay if delay else 0, failures, host),
                )
        finally:
            db.close()

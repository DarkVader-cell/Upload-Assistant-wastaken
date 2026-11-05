"""Durable catalogue jobs and an immutable daily-start ledger."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path


def job_key(candidate: dict) -> str:
    imdb = candidate.get("imdb")
    if not isinstance(imdb, str) or not re.fullmatch(r"tt\d{7,10}", imdb):
        raise ValueError("An exact IMDb identity is required")
    kind = candidate.get("media_type", "movie")
    if kind == "movie":
        key = imdb
    elif kind == "series":
        key = "series:" + imdb
    elif kind == "episode":
        season, episode = candidate.get("season"), candidate.get("episode")
        if type(season) is not int or season < 0 or type(episode) is not int or episode < 1:
            raise ValueError("Exact integer season/episode numbers are required")
        key = f"{imdb}:S{season:02}E{episode:02}"
    else:
        raise ValueError("Unsupported media type")
    if candidate.get("job_key", key) != key:
        raise ValueError("Job identity does not match its metadata")
    return key


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
 job_key TEXT PRIMARY KEY, imdb TEXT NOT NULL, candidate TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending', discovered REAL NOT NULL, checked REAL,
 evidence TEXT, started_day TEXT, service TEXT, reason TEXT NOT NULL DEFAULT '',
 next_check REAL NOT NULL DEFAULT 0, error_count INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS cursors (key TEXT PRIMARY KEY,cursor TEXT);
CREATE TABLE IF NOT EXISTS attempts (
 id INTEGER PRIMARY KEY AUTOINCREMENT,job_key TEXT NOT NULL,day TEXT NOT NULL,
 service TEXT NOT NULL,started REAL NOT NULL);
CREATE INDEX IF NOT EXISTS jobs_ready ON jobs(status,next_check,checked,discovered);
CREATE INDEX IF NOT EXISTS jobs_daily ON jobs(started_day,service);
CREATE INDEX IF NOT EXISTS jobs_activity ON jobs(coalesce(checked,discovered) DESC,job_key);
CREATE INDEX IF NOT EXISTS jobs_title ON jobs(imdb);
CREATE INDEX IF NOT EXISTS attempts_daily ON attempts(day,service);
"""


class Store:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path, timeout=5)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.row_factory = sqlite3.Row
        self.db.execute("BEGIN IMMEDIATE")
        try:
            columns = {row[1] for row in self.db.execute("PRAGMA table_info(jobs)")}
            legacy = bool(columns) and "job_key" not in columns
            if legacy:
                if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='jobs_v1_backup'").fetchone():
                    raise ValueError("Existing migration backup requires manual verification")
                self.db.execute("ALTER TABLE jobs RENAME TO jobs_v1_backup")
                for name in ("jobs_ready", "jobs_daily", "jobs_activity"):
                    self.db.execute("DROP INDEX IF EXISTS " + name)
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    self.db.execute(statement)
            if legacy:
                self.db.execute("""INSERT INTO jobs(job_key,imdb,candidate,status,discovered,checked,evidence,started_day,service,reason)
                    SELECT imdb,imdb,candidate,status,discovered,checked,evidence,started_day,service,reason FROM jobs_v1_backup""")
                self.db.execute("""INSERT INTO attempts(job_key,day,service,started)
                    SELECT job_key,started_day,service,coalesce(checked,discovered) FROM jobs WHERE started_day IS NOT NULL""")
            self.db.commit()
        except Exception:
            self.db.rollback()
            self.db.close()
            raise

    def add(self, candidate: dict):
        key = job_key(candidate)
        candidate = {**candidate, "job_key": key, "media_type": candidate.get("media_type", "movie")}
        previous = self.db.execute("SELECT candidate,status,evidence,checked,reason FROM jobs WHERE job_key=?", (key,)).fetchone()
        keep_tracker_hit = False
        if previous:
            prior = json.loads(previous[0])
            try:
                evidence = json.loads(previous["evidence"] or "{}")
                inventory = evidence.get("inventory", {})
                keep_tracker_hit = (
                    previous["status"] == "blocked"
                    and (previous["reason"] or "").startswith("Exact title already exists on ")
                    and previous["checked"] is not None
                    and 0 <= time.time() - previous["checked"] < 6 * 3600
                    and isinstance(inventory, dict)
                    and "present" in inventory.values()
                    and all(prior.get(field) == candidate.get(field) for field in ("imdb", "service", "region", "item", "origin_countries", "media_type"))
                )
            except (ValueError, TypeError, AttributeError):
                keep_tracker_hit = False
            if (
                prior.get("imdb") == candidate["imdb"]
                and prior.get("media_type", "movie") == candidate["media_type"]
                and prior.get("original_language_source") == "tmdb_imdb_v1"
            ):
                candidate.update(original_language=prior.get("original_language"), original_language_source="tmdb_imdb_v1")
        self.db.execute(
            """INSERT INTO jobs(job_key,imdb,candidate,discovered,service) VALUES(?,?,?,?,?)
            ON CONFLICT(job_key) DO UPDATE SET candidate=excluded.candidate,discovered=excluded.discovered,
            service=excluded.service,status=CASE WHEN ? THEN 'blocked' WHEN jobs.status='unknown' THEN 'unknown' ELSE 'pending' END,
            next_check=CASE WHEN jobs.status='unknown' THEN jobs.next_check ELSE 0 END,
            error_count=CASE WHEN jobs.status='unknown' THEN jobs.error_count ELSE 0 END
            WHERE jobs.status IN ('stale','pending','ready','unknown','blocked','review','expanded')
            AND jobs.started_day IS NULL""",
            (key, candidate["imdb"], json.dumps(candidate), time.time(), candidate["service"], int(keep_tracker_hit)),
        )

    def cursor(self, key: str):
        row = self.db.execute("SELECT cursor FROM cursors WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def page(self, key: str, candidates: list[dict], cursor: str | None):
        with self.db:
            for candidate in candidates:
                self.add(candidate)
            self.db.execute("INSERT OR REPLACE INTO cursors VALUES(?,?)", (key, cursor))

    def update(self, key: str, status: str, reason: str = "", evidence=None):
        with self.db:
            row = self.db.execute("SELECT error_count FROM jobs WHERE job_key=?", (key,)).fetchone()
            if row is None:
                raise ValueError("Job not found")
            errors = row[0] + 1 if status == "unknown" else 0
            next_check = time.time() + min(21600, 60 * 2 ** min(errors - 1, 10)) if errors else 0
            self.db.execute(
                """UPDATE jobs SET status=?,reason=?,checked=?,evidence=?,error_count=?,next_check=? WHERE job_key=?""",
                (status, reason, time.time(), json.dumps(evidence), errors, next_check, key),
            )

    def reserve(self, key: str, service: str, total_limit: int, service_limit: int) -> bool:
        # BEGIN IMMEDIATE makes the check+reservation atomic even across processes.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            day = datetime.now(UTC).date().isoformat()
            total = self.db.execute("SELECT count(*) FROM attempts WHERE day=?", (day,)).fetchone()[0]
            count = self.db.execute("SELECT count(*) FROM attempts WHERE day=? AND service=?", (day, service)).fetchone()[0]
            row = self.db.execute("SELECT status,started_day,service,candidate FROM jobs WHERE job_key=?", (key,)).fetchone()
            if (
                total >= total_limit
                or count >= service_limit
                or row is None
                or row["service"] != service
                or row["status"] not in {"pending", "ready", "unknown"}
                or row["started_day"] is not None
            ):
                self.db.rollback()
                return False
            if json.loads(row["candidate"]).get("media_type") == "series":
                self.db.rollback()
                return False
            self.db.execute("INSERT INTO attempts(job_key,day,service,started) VALUES(?,?,?,?)", (key, day, service, time.time()))
            self.db.execute("UPDATE jobs SET status='started',started_day=?,reason='' WHERE job_key=?", (day, key))
            self.db.commit()
            return True
        except Exception:
            self.db.rollback()
            raise

    def episode_keys(self, imdb: str) -> frozenset[str]:
        return frozenset(row[0] for row in self.db.execute("SELECT job_key FROM jobs WHERE imdb=? AND job_key!=?", (imdb, "series:" + imdb)))

    def invalidate_unstarted(self):
        with self.db:
            self.db.execute(
                "UPDATE jobs SET status='pending',reason='Rules changed; fresh verification required',checked=NULL,next_check=0,error_count=0 WHERE started_day IS NULL AND status NOT IN ('started','succeeded','failed','uncertain')"
            )

    def defer_series(self, key: str, count: int, minutes: int):
        with self.db:
            self.db.execute(
                "UPDATE jobs SET status='expanded',reason=?,checked=?,next_check=? WHERE job_key=? AND started_day IS NULL",
                (f"Series checked; {count} new episode jobs discovered", time.time(), time.time() + minutes * 60, key),
            )

    def episode_states(self, imdb: str) -> dict[str, str]:
        return dict(self.db.execute("SELECT job_key,status FROM jobs WHERE imdb=? AND job_key!=?", (imdb, "series:" + imdb)).fetchall())

    def usage(self, service=None):
        day = datetime.now(UTC).date().isoformat()
        total = self.db.execute("SELECT count(*) FROM attempts WHERE day=?", (day,)).fetchone()[0]
        count = self.db.execute("SELECT count(*) FROM attempts WHERE day=? AND service=?", (day, service)).fetchone()[0] if service else 0
        return total, count

    def requeue(self, key: str, verified=False):
        """Explicit recovery only; never erase attempt history or manufacture a fresh offer."""
        with self.db:
            row = self.db.execute("SELECT status,started_day FROM jobs WHERE job_key=?", (key,)).fetchone()
            if not row:
                raise ValueError("Job not found")
            if row[0] == "started":
                raise ValueError("A started job requires an external process/payload check; it cannot be replayed here")
            if row[0] == "succeeded":
                raise ValueError("Completed downloads cannot be automatically requeued")
            if row[1] is not None and not verified:
                raise ValueError("Confirm that the previous process is stopped and no completed payload exists")
            self.db.execute("UPDATE jobs SET status='pending',started_day=NULL,next_check=0,error_count=0,reason='Explicit recheck requested' WHERE job_key=?", (key,))

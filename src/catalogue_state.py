"""Bounded, read-only queue views with short, mutation-aware caches."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path

STATUSES = frozenset({"pending", "ready", "unknown", "blocked", "stale", "started", "succeeded", "failed", "uncertain", "review", "expanded", "filtered", "unavailable"})
SERVICES = frozenset({"amazon", "netflix", "appletv"})


class QueueReader:
    def __init__(self, path: Path, ttl: float = 2):
        self.path, self.ttl = path, ttl
        self.cache = OrderedDict()
        self.lock = threading.Lock()

    def revision(self):
        parts = [datetime.now(UTC).date().isoformat()]
        for path in (self.path, self.path.with_name(self.path.name + "-wal")):
            try:
                stat = path.stat()
                parts.append((stat.st_ino, stat.st_size, stat.st_mtime_ns))
            except FileNotFoundError:
                parts.append(None)
        return hashlib.sha256(repr(parts).encode()).hexdigest()[:20]

    def _cached(self, key, calculate):
        with self.lock:
            now = time.monotonic()
            hit = self.cache.get(key)
            if hit and now - hit[0] < self.ttl:
                self.cache.move_to_end(key)
                return hit[1]
            result = calculate()
            self.cache[key] = (now, result)
            self.cache.move_to_end(key)
            while len(self.cache) > 32:
                self.cache.popitem(last=False)
            return result

    def _connect(self):
        db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
        db.row_factory = sqlite3.Row
        db.create_function("casefold", 1, lambda value: str(value or "").casefold(), deterministic=True)
        return db

    def summary(self):
        revision = self.revision()

        def calculate():
            if not self.path.exists():
                return {"revision": revision, "counts": {}, "starts_today": 0, "service_starts_today": {}, "total": 0}
            db = self._connect()
            try:
                counts = dict(db.execute("SELECT status,count(*) FROM jobs GROUP BY status").fetchall())
                day = datetime.now(UTC).date().isoformat()
                ledger = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='attempts'").fetchone()
                starts = (
                    dict(db.execute("SELECT service,count(*) FROM attempts WHERE day=? GROUP BY service", (day,)).fetchall())
                    if ledger
                    else dict(db.execute("SELECT service,count(*) FROM jobs WHERE started_day=? GROUP BY service", (day,)).fetchall())
                )
                return {"revision": revision, "counts": counts, "starts_today": sum(starts.values()), "service_starts_today": starts, "total": sum(counts.values())}
            finally:
                db.close()

        return self._cached((revision, "summary"), calculate)

    def selection(self, settings):
        from src.catalogue_diagnostics import selection_summary

        def calculate():
            if not self.path.exists():
                return selection_summary(None, settings)
            db = self._connect()
            try:
                return selection_summary(db, settings)
            finally:
                db.close()

        keys = (
            "services",
            "origin_countries",
            "media_types",
            "min_release_year",
            "max_release_year",
            "min_imdb_votes",
            "max_imdb_votes",
            "min_runtime_minutes",
            "max_runtime_minutes",
            "original_languages",
            "exclude_title_keywords",
            "max_candidate_age_hours",
            "require_prime_inclusion",
        )
        return self._cached((self.revision(), "selection", json.dumps({key: settings.get(key) for key in keys}, sort_keys=True)), calculate)

    def page(self, page=1, page_size=25, status="", service="", query="", filters=None):
        if type(page) is not int or not 1 <= page <= 1000000 or type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("Invalid pagination")
        if (status and status not in STATUSES) or (service and service not in SERVICES):
            raise ValueError("Invalid queue filter")
        if not isinstance(query, str) or len(query) > 120:
            raise ValueError("Search must be at most 120 characters")
        from src.catalogue_query import extra_filters

        extra_filters(None, filters)
        query = query.strip()
        revision = self.revision()

        def calculate():
            empty = {"revision": revision, "jobs": [], "total": 0, "page": page, "page_size": page_size, "pages": 1}
            if not self.path.exists():
                return empty
            clauses, parameters = [], []
            if status:
                clauses.append("status=?")
                parameters.append(status)
            if service:
                clauses.append("service=?")
                parameters.append(service)
            if query:
                escaped = query.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                clauses.append("(casefold(json_extract(candidate,'$.title')) LIKE ? ESCAPE '\\' OR imdb LIKE ? ESCAPE '\\')")
                parameters.extend([f"%{escaped}%", f"%{escaped}%"])
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            db = self._connect()
            try:
                extra, values, order, _key = extra_filters(db, filters)
                clauses.extend(extra)
                parameters.extend(values)
                where = " WHERE " + " AND ".join(clauses) if clauses else ""
                # The SQL fragments are fixed above; every client value is bound.
                total = db.execute("SELECT count(*) FROM jobs" + where, parameters).fetchone()[0]  # noqa: S608
                sql = "SELECT job_key,imdb,candidate,status,reason,started_day,checked FROM jobs" + where + " ORDER BY " + order + " LIMIT ? OFFSET ?"  # noqa: S608
                rows = db.execute(sql, [*parameters, page_size, (page - 1) * page_size]).fetchall()
                jobs = []
                for row in rows:
                    candidate = json.loads(row["candidate"])
                    from src.catalogue_access import access_state

                    access = access_state(db, candidate, row["job_key"])
                    jobs.append(
                        {
                            "key": row["job_key"],
                            "imdb": row["imdb"],
                            "title": candidate.get("title"),
                            "year": candidate.get("year"),
                            "imdb_votes": candidate.get("imdb_votes"),
                            "runtime_minutes": candidate.get("runtime_minutes"),
                            "original_language": candidate.get("original_language"),
                            "service": candidate.get("service"),
                            "region": candidate.get("region"),
                            "source_access": access,
                            "provider_item": candidate.get("item"),
                            "media_type": candidate.get("media_type", "movie"),
                            "season": candidate.get("season"),
                            "episode": candidate.get("episode"),
                            "status": row["status"],
                            "reason": row["reason"],
                            "started_day": row["started_day"],
                        }
                    )
                return {**empty, "jobs": jobs, "total": total, "pages": max(1, (total + page_size - 1) // page_size)}
            finally:
                db.close()

        return self._cached((revision, page, page_size, status, service, query, json.dumps(filters, sort_keys=True)), calculate)

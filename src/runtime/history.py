"""Persistent, searchable release execution history.

The store deliberately keeps a compact, non-secret projection of each run.
SQLite gives CLI, Web UI, and detached Qui processes safe concurrent access
without coupling history retention to temporary execution directories.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from src.runtime.state import default_config

HISTORY_VERSION = 1
_TERMINAL_STATUSES = {"cancelled", "completed", "debug", "failed", "interrupted", "skipped"}


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else str(value).strip() if value is not None else ""


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_text(item) for item in value if _text(item)]
    return []


def release_status(meta: Mapping[str, Any] | Any) -> str:
    """Derive a stable history status from Upload-Assistant tracker results."""
    getter = meta.get if hasattr(meta, "get") else lambda _key, default=None: default
    if bool(getter("debug", False)):
        return "debug"
    statuses = getter("tracker_status", {})
    if isinstance(statuses, Mapping):
        values = [item for item in statuses.values() if isinstance(item, Mapping)]
        if any(item.get("upload_success") is True for item in values):
            return "completed"
        if values and any(item.get("upload") is True or item.get("upload_success") is False for item in values):
            return "failed"
        if values:
            return "skipped"
    return "completed"


class ReleaseHistoryStore:
    """Store compact release records and query them without loading all rows."""

    def __init__(self, base_dir: str | Path, config: Mapping[str, Any] | None = None) -> None:
        settings = default_config(config)
        self.enabled = bool(settings.get("release_history_enabled", True))
        configured = Path(str(settings.get("release_history_db", "data/cache/release_history.sqlite3")))
        base = Path(base_dir).expanduser().resolve()
        self.path = configured if configured.is_absolute() else base / configured
        try:
            self.max_entries = max(100, int(settings.get("release_history_max_entries", 5000)))
        except (TypeError, ValueError):
            self.max_entries = 5000
        self._initialized = False
        self._initialize_lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        if not self._initialized:
            with self._initialize_lock:
                if not self._initialized:
                    connection.execute("PRAGMA journal_mode=WAL")
                    connection.execute(
                        """
                        CREATE TABLE IF NOT EXISTS release_history (
                            id TEXT PRIMARY KEY,
                            version INTEGER NOT NULL,
                            created_at REAL NOT NULL,
                            updated_at REAL NOT NULL,
                            source TEXT NOT NULL DEFAULT '',
                            source_path TEXT NOT NULL DEFAULT '',
                            release_name TEXT NOT NULL DEFAULT '',
                            category TEXT NOT NULL DEFAULT '',
                            media_type TEXT NOT NULL DEFAULT '',
                            resolution TEXT NOT NULL DEFAULT '',
                            status TEXT NOT NULL DEFAULT '',
                            trackers TEXT NOT NULL DEFAULT '[]',
                            successful_trackers TEXT NOT NULL DEFAULT '[]',
                            failed_trackers TEXT NOT NULL DEFAULT '[]',
                            tracker_uploads TEXT NOT NULL DEFAULT '[]',
                            external_ids TEXT NOT NULL DEFAULT '{}',
                            job_id TEXT NOT NULL DEFAULT ''
                        )
                        """
                    )
                    columns = {row[1] for row in connection.execute("PRAGMA table_info(release_history)")}
                    if "tracker_uploads" not in columns:
                        connection.execute("ALTER TABLE release_history ADD COLUMN tracker_uploads TEXT NOT NULL DEFAULT '[]'")
                    connection.execute("CREATE INDEX IF NOT EXISTS release_history_updated_idx ON release_history(updated_at DESC)")
                    connection.execute("CREATE INDEX IF NOT EXISTS release_history_status_idx ON release_history(status, updated_at DESC)")
                    connection.commit()
                    self._initialized = True
        return connection

    @staticmethod
    def _tracker_projection(meta: Mapping[str, Any] | Any) -> tuple[list[str], list[str], list[str]]:
        getter = meta.get if hasattr(meta, "get") else lambda _key, default=None: default
        trackers = _string_list(getter("trackers", []))
        successful: list[str] = []
        failed: list[str] = []
        statuses = getter("tracker_status", {})
        if isinstance(statuses, Mapping):
            for tracker, value in statuses.items():
                if not isinstance(value, Mapping):
                    continue
                name = _text(tracker)
                if value.get("upload_success") is True:
                    successful.append(name)
                elif value.get("upload_success") is False:
                    failed.append(name)
        return trackers, successful, failed

    @staticmethod
    def _tracker_upload_projection(meta: Mapping[str, Any] | Any) -> list[dict[str, str]]:
        """Return the non-secret submitted title/link projection for successful uploads."""
        getter = meta.get if hasattr(meta, "get") else lambda _key, default=None: default
        statuses = getter("tracker_status", {})
        if not isinstance(statuses, Mapping):
            return []
        uploads: list[dict[str, str]] = []
        for tracker, value in statuses.items():
            if not isinstance(value, Mapping) or value.get("upload_success") is not True:
                continue
            item = {"tracker": _text(tracker)}
            submitted_name = _text(value.get("upload_name"))
            submitted_url = _text(value.get("upload_url"))
            if submitted_name:
                item["name"] = submitted_name
            if submitted_url:
                item["url"] = submitted_url
            uploads.append(item)
        return sorted(uploads, key=lambda item: item["tracker"])

    @staticmethod
    def _external_ids(meta: Mapping[str, Any] | Any) -> dict[str, str]:
        getter = meta.get if hasattr(meta, "get") else lambda _key, default=None: default
        values: dict[str, str] = {}
        for key in ("imdb_id", "tmdb_id", "tvdb_id", "mal_id", "anilist_id"):
            value = _text(getter(key, ""))
            if value and value != "0":
                values[key] = value
        return values

    def _upsert(self, record: Mapping[str, Any]) -> None:
        if not self.enabled:
            return
        now = time.time()
        values = {
            "id": _text(record.get("id")),
            "version": HISTORY_VERSION,
            "created_at": float(record.get("created_at") or now),
            "updated_at": float(record.get("updated_at") or now),
            "source": _text(record.get("source")),
            "source_path": _text(record.get("source_path")),
            "release_name": _text(record.get("release_name")),
            "category": _text(record.get("category")),
            "media_type": _text(record.get("media_type")),
            "resolution": _text(record.get("resolution")),
            "status": _text(record.get("status")),
            "trackers": json.dumps(record.get("trackers") or []),
            "successful_trackers": json.dumps(record.get("successful_trackers") or []),
            "failed_trackers": json.dumps(record.get("failed_trackers") or []),
            "tracker_uploads": json.dumps(record.get("tracker_uploads") or []),
            "external_ids": json.dumps(record.get("external_ids") or {}),
            "job_id": _text(record.get("job_id")),
        }
        if not values["id"]:
            return
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO release_history (
                    id, version, created_at, updated_at, source, source_path,
                    release_name, category, media_type, resolution, status,
                    trackers, successful_trackers, failed_trackers, tracker_uploads, external_ids, job_id
                ) VALUES (
                    :id, :version, :created_at, :updated_at, :source, :source_path,
                    :release_name, :category, :media_type, :resolution, :status,
                    :trackers, :successful_trackers, :failed_trackers, :tracker_uploads, :external_ids, :job_id
                )
                ON CONFLICT(id) DO UPDATE SET
                    updated_at=excluded.updated_at,
                    source=CASE WHEN excluded.source != '' THEN excluded.source ELSE release_history.source END,
                    source_path=CASE WHEN excluded.source_path != '' THEN excluded.source_path ELSE release_history.source_path END,
                    release_name=CASE WHEN excluded.release_name != '' THEN excluded.release_name ELSE release_history.release_name END,
                    category=CASE WHEN excluded.category != '' THEN excluded.category ELSE release_history.category END,
                    media_type=CASE WHEN excluded.media_type != '' THEN excluded.media_type ELSE release_history.media_type END,
                    resolution=CASE WHEN excluded.resolution != '' THEN excluded.resolution ELSE release_history.resolution END,
                    status=CASE WHEN excluded.status != '' THEN excluded.status ELSE release_history.status END,
                    trackers=CASE WHEN excluded.trackers != '[]' THEN excluded.trackers ELSE release_history.trackers END,
                    successful_trackers=CASE WHEN excluded.successful_trackers != '[]' THEN excluded.successful_trackers ELSE release_history.successful_trackers END,
                    failed_trackers=CASE WHEN excluded.failed_trackers != '[]' THEN excluded.failed_trackers ELSE release_history.failed_trackers END,
                    tracker_uploads=CASE WHEN excluded.tracker_uploads != '[]' THEN excluded.tracker_uploads ELSE release_history.tracker_uploads END,
                    external_ids=CASE WHEN excluded.external_ids != '{}' THEN excluded.external_ids ELSE release_history.external_ids END,
                    job_id=CASE WHEN excluded.job_id != '' THEN excluded.job_id ELSE release_history.job_id END
                """,
                values,
            )
            connection.execute(
                "DELETE FROM release_history WHERE id IN (SELECT id FROM release_history ORDER BY updated_at DESC LIMIT -1 OFFSET ?)",
                (self.max_entries,),
            )

    def record_release(
        self,
        meta: Mapping[str, Any] | Any,
        *,
        status: str | None = None,
        source: str = "cli",
        record_id: str = "",
    ) -> str:
        getter = meta.get if hasattr(meta, "get") else lambda _key, default=None: default
        job_id = _text(os.environ.get("UA_DETACHED_JOB_ID", ""))
        session_id = _text(getter("webui_session_id", ""))
        release_id = _text(record_id) or job_id or session_id or _text(getter("uuid", ""))
        if not release_id:
            release_id = f"release-{time.time_ns()}"
        trackers, successful, failed = self._tracker_projection(meta)
        source_path = _text(getter("path", ""))
        self._upsert(
            {
                "id": release_id,
                "source": "qui" if job_id else source,
                "source_path": source_path,
                "release_name": _text(getter("name", "")) or Path(source_path).name,
                "category": _text(getter("category", "")),
                "media_type": _text(getter("type", "")) or _text(getter("is_disc", "")),
                "resolution": _text(getter("resolution", "")),
                "status": status or release_status(meta),
                "trackers": trackers,
                "successful_trackers": successful,
                "failed_trackers": failed,
                "tracker_uploads": self._tracker_upload_projection(meta),
                "external_ids": self._external_ids(meta),
                "job_id": job_id,
            }
        )
        return release_id

    def record_job(self, job: Mapping[str, Any]) -> None:
        status = _text(job.get("status"))
        if not status:
            return
        self._upsert(
            {
                "id": _text(job.get("id")),
                "created_at": _iso_or_epoch(job.get("created_at")),
                "updated_at": _iso_or_epoch(job.get("finished_at")) or time.time(),
                "source": "qui",
                "source_path": _text(job.get("source_path")),
                "release_name": Path(_text(job.get("source_path"))).name,
                "status": status,
                "job_id": _text(job.get("id")),
            }
        )

    def search(self, query: str = "", status: str = "", *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        if not self.enabled or not self.path.exists():
            return []
        clauses: list[str] = []
        parameters: list[object] = []
        cleaned_query = query.strip()
        if cleaned_query:
            pattern = f"%{cleaned_query}%"
            clauses.append("(release_name LIKE ? OR source_path LIKE ? OR id LIKE ? OR job_id LIKE ? OR trackers LIKE ?)")
            parameters.extend([pattern] * 5)
        cleaned_status = status.strip().casefold()
        if cleaned_status:
            clauses.append("status = ?")
            parameters.append(cleaned_status)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM release_history{where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",  # noqa: S608 - fixed clauses only
                parameters,
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            for key, fallback in (("trackers", []), ("successful_trackers", []), ("failed_trackers", []), ("tracker_uploads", []), ("external_ids", {})):
                try:
                    item[key] = json.loads(item[key])
                except (TypeError, ValueError):
                    item[key] = fallback
            item["terminal"] = item.get("status") in _TERMINAL_STATUSES
            results.append(item)
        return results

    def stats(self) -> dict[str, int]:
        if not self.enabled or not self.path.exists():
            return {"entries": 0, "completed": 0, "failed": 0}
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS entries, SUM(status = 'completed') AS completed, SUM(status = 'failed') AS failed FROM release_history"
            ).fetchone()
        return {key: int(row[key] or 0) for key in ("entries", "completed", "failed")}


def _iso_or_epoch(value: object) -> float:
    text = _text(value)
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        pass
    try:
        from datetime import datetime

        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0

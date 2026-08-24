"""Cursor-based event synchronization for Qui and other queue consumers."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from flask import Blueprint, jsonify, request


@dataclass(slots=True)
class QuiEventBroker:
    limit: int = 1000
    _sequence: int = 0
    _events: deque[dict[str, Any]] = field(default_factory=deque)
    _condition: threading.Condition = field(default_factory=threading.Condition)

    def publish(self, event_type: str, job_id: str, job: Mapping[str, Any]) -> int:
        with self._condition:
            self._sequence += 1
            event = {
                "cursor": self._sequence,
                "type": event_type,
                "job_id": job_id,
                "timestamp": time.time(),
                "job": {key: value for key, value in job.items() if key != "command"},
            }
            self._events.append(event)
            while len(self._events) > self.limit:
                self._events.popleft()
            self._condition.notify_all()
            return self._sequence

    def poll(self, cursor: int, timeout: float = 0.0) -> tuple[int, list[dict[str, Any]]]:
        deadline = time.monotonic() + max(0.0, min(timeout, 25.0))
        with self._condition:
            while self._sequence <= cursor and timeout > 0:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            return self._sequence, [dict(event) for event in self._events if int(event["cursor"]) > cursor]


def progress_from_log_line(line: str) -> dict[str, Any] | None:
    import re

    match = re.search(r"(?:Processed|uploaded)\s+(\d+)\s*(?:/|of)\s*(\d+)", line, re.IGNORECASE)
    if match:
        completed, total = (int(value) for value in match.groups())
        return {"completed": completed, "total": total, "percent": round(completed * 100 / total, 1) if total else 0.0}
    if "Gathering info for" in line:
        return {"stage": "preparing", "detail": line.strip()}
    if "All tracker uploads processed" in line:
        return {"stage": "finalizing", "percent": 95.0}
    return None


def create_qui_sync_blueprint(*, auth_check: Any, broker: QuiEventBroker, snapshots: Any, retry_job: Any) -> Blueprint:
    blueprint = Blueprint("qui_sync", __name__)

    @blueprint.route("/api/qui/events")
    def events():
        ok, response = auth_check()
        if not ok:
            return response
        try:
            cursor = max(0, int(request.args.get("cursor", "0")))
            wait = max(0.0, min(float(request.args.get("wait", "0")), 25.0))
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "cursor and wait must be numeric"}), 400
        next_cursor, queued_events = broker.poll(cursor, wait)
        return jsonify({"success": True, "cursor": next_cursor, "events": queued_events})

    @blueprint.route("/api/qui/summary")
    def summary():
        ok, response = auth_check()
        if not ok:
            return response
        jobs = snapshots(limit=500)
        counts: dict[str, int] = {}
        for job in jobs:
            status = str(job.get("status", "unknown"))
            counts[status] = counts.get(status, 0) + 1
        active = sum(counts.get(status, 0) for status in ("starting", "running", "waiting_for_input", "waiting_for_metadata", "waiting_for_release_metadata"))
        return jsonify({"success": True, "counts": counts, "active": active, "queued": counts.get("queued", 0), "total": len(jobs)})

    @blueprint.route("/api/qui/retry", methods=["POST"])
    def retry_failed():
        ok, response = auth_check()
        if not ok:
            return response
        data = request.get_json(silent=True)
        data = data if isinstance(data, dict) else {}
        requested = data.get("job_ids")
        if requested is not None and (not isinstance(requested, list) or not all(isinstance(item, str) for item in requested)):
            return jsonify({"success": False, "error": "job_ids must be a list of strings"}), 400
        candidates = requested if isinstance(requested, list) else [
            str(job["id"]) for job in snapshots(limit=500) if str(job.get("status")) in {"failed", "interrupted"}
        ]
        retried = [job_id for job_id in candidates if retry_job(job_id)]
        return jsonify({"success": True, "retried": retried, "count": len(retried)}), 202 if retried else 200

    return blueprint

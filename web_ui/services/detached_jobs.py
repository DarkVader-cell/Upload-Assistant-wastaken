"""Pure detached-job validation, restoration, and presentation logic."""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True, frozen=True)
class RestoredDetachedJobs:
    jobs: dict[str, dict[str, Any]]
    queue: list[str]


def restore_detached_jobs(path: Path) -> RestoredDetachedJobs | None:
    if not path.exists():
        return None
    try:
        stored: Any = json.loads(path.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError, TypeError:
        return None
    if not isinstance(stored, Mapping):
        return None

    jobs: dict[str, dict[str, Any]] = {}
    queue: list[str] = []
    for raw_job_id, raw_job in stored.items():
        job_id = str(raw_job_id)
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", job_id) or not isinstance(raw_job, Mapping):
            continue
        job = dict(raw_job)
        command = job.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
            continue
        status = str(job.get("status", ""))
        if status == "queued":
            queue.append(job_id)
            job["message"] = "Recovered after WebUI restart; queued for unattended execution"
        elif status in {"running", "waiting_for_input", "waiting_for_metadata", "waiting_for_release_metadata"}:
            job["status"] = "interrupted"
            job["message"] = "Interrupted by WebUI restart; retained for safe retry"
            job["recovery_available"] = True
            job["finished_at"] = datetime.now(UTC).isoformat()
            job["metadata_request"] = None
            job["release_metadata_request"] = None
            job["prompt_request"] = None
        jobs[job_id] = job
    return RestoredDetachedJobs(jobs, queue)


def snapshot_detached_jobs(
    jobs: Mapping[str, Mapping[str, Any]],
    queue: Sequence[str],
    *,
    limit: int,
    json_safe: Callable[[object], Any],
) -> list[dict[str, Any]]:
    values = [dict(job) for job in jobs.values()]
    queue_positions = {job_id: index + 1 for index, job_id in enumerate(queue)}
    values.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
    snapshots: list[dict[str, Any]] = []
    for job in values[:limit]:
        snapshot = {key: value for key, value in job.items() if key != "command"}
        job_id = str(job.get("id", ""))
        status = str(job.get("status"))
        snapshot["queue_position"] = queue_positions.get(job_id)
        snapshot["can_edit"] = status in {"queued", "interrupted", "failed"}
        snapshot["can_cancel"] = status in {"queued", "starting", "running", "waiting_for_input", "waiting_for_metadata", "waiting_for_release_metadata"}
        snapshot["can_retry"] = status in {"failed", "interrupted"}
        snapshots.append(json_safe(snapshot))
    return snapshots


def validate_detached_args(
    raw_args: object,
    append_unattended: object,
    validator: Callable[[Sequence[object]], list[str]],
) -> tuple[list[str], str]:
    arguments = str(raw_args or "")
    append = str(append_unattended).strip().lower() not in {"0", "false", "no", "off"}
    parsed_args = shlex.split(arguments)
    if append and "-ua" not in parsed_args and "--unattended" not in parsed_args:
        parsed_args.append("-ua")
    validated_args = validator(parsed_args)
    return validated_args, " ".join(validated_args)

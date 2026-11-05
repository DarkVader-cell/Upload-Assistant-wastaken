"""Fail-closed wrapper around the installed Upload Assistant slot rules."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from contextlib import suppress
from pathlib import Path

from src.catalogue_runner import RunnerError

BRIDGE = Path(__file__).resolve().parents[1] / "tools/catalogue-slot-bridge.py"


def eligible(evidence: dict, mode: str, trackers: list[str]) -> bool:
    if not isinstance(evidence, dict) or set(evidence) != set(trackers):
        return False
    relevant = [value for value in evidence.values() if value.get("state") != "not_applicable"]
    if not relevant:
        return False
    absent = [value for value in relevant if value.get("state") == "absent"]
    if mode == "absent_all":
        return len(absent) == len(relevant)
    if mode == "missing_any":
        return bool(absent)
    if mode == "missing_or_free_slot":
        return bool(absent) or any(value.get("state") == "allow" and value.get("requires_evidence") is False and value.get("trump") is False for value in relevant)
    return False


class SlotChecker:
    def __init__(self, settings: dict):
        self.settings = settings

    def check(self, candidate: dict, profile: dict) -> dict:
        root = self.settings.get("ua_root")
        if not root or not (Path(root) / "src/slot_rules/registry.py").is_file():
            raise RunnerError("Configure the installed UA source root before slot checking")
        arguments = [
            sys.executable,
            str(BRIDGE),
            "--ua-root",
            str(root),
            "--ua-config",
            self.settings["ua_config"],
            "--rate-state",
            str(Path(self.settings["state_dir"]).expanduser() / "api-rate.sqlite3"),
        ]
        request = json.dumps(
            {
                "schema": 1,
                "candidate": candidate,
                "profile": profile,
                "trackers": self.settings["trackers"],
                "stop_on_hit": self.settings.get("eligibility", "absent_all") == "absent_all",
                "rate_interval": self.settings.get("tracker_request_interval_seconds", 10),
                "rate_daily_limit": self.settings.get("tracker_daily_api_limit", 200),
            }
        )
        child = None
        try:
            child = subprocess.Popen(  # noqa: S603 -- fixed adapter, trusted server paths; data travels as stdin JSON
                arguments,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                start_new_session=True,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            output, _ = child.communicate(request, timeout=self.settings.get("slot_timeout_seconds", 180))
            if child.returncode or len(output) > 1024 * 1024:
                raise RunnerError("UA slot adapter failed or exceeded its result limit")
            data = json.loads(output)
            states = data.get("trackers")
            if data.get("schema") != 1 or not isinstance(states, dict) or set(states) != set(self.settings["trackers"]):
                raise RunnerError("UA slot adapter returned incomplete evidence")
            if any(not isinstance(value, dict) or value.get("state") not in {"absent", "allow", "block", "review", "unknown", "not_applicable"} for value in states.values()):
                raise RunnerError("UA slot adapter returned invalid states")
            return states
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
            if child:
                with suppress(ProcessLookupError):
                    os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    with suppress(ProcessLookupError):
                        os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
            if isinstance(exc, KeyboardInterrupt):
                raise
            raise RunnerError("UA slot check timed out; occupancy remains unknown") from None
        except (OSError, ValueError):
            raise RunnerError("UA slot check failed; occupancy remains unknown") from None

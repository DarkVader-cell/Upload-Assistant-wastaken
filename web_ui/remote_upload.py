"""Authenticated remote-upload control plane; backend secrets never reach browsers."""
# ruff: noqa: S603 -- fixed interpreter/module, validated argument lists, no shell
from __future__ import annotations

import json
import math
import os
import shlex
import subprocess
import sys
import uuid
from pathlib import Path

from flask import Blueprint, jsonify, redirect, request

from src.config_io import atomic_write_text


def backends():
    """Operator-controlled mapping, never accept config filenames from HTTP."""
    path = os.environ.get("UA_REMOTE_UPLOAD_BACKENDS")
    if not path:
        return {}
    values = json.loads(Path(path).read_text())
    if not isinstance(values, dict):
        raise ValueError("Backend registry must be an object")
    return {name: Path(config).expanduser() for name, config in values.items() if isinstance(name, str) and isinstance(config, str)}


def create_blueprint(*, authenticated, csrf_valid, same_origin, csrf_token):
    del csrf_token  # Native workspace uses the main application's CSRF token.
    bp = Blueprint("remote_upload", __name__)

    @bp.before_request
    def protect():
        if not authenticated():
            return jsonify(error="Authentication required"), 401
        if request.method == "POST" and (not csrf_valid() or not same_origin()):
            return jsonify(error="Invalid request origin or CSRF token"), 403
        return None

    @bp.get("/remote-upload")
    def page():
        return redirect('/?workspace=remote')

    @bp.get("/api/remote-upload")
    def status():
        result = {}
        try:
            for name, path in backends().items():
                cfg = json.loads(path.read_text())
                state = Path(cfg["state_dir"]).expanduser()
                ledger = state / "ledger.json"
                data = json.loads(ledger.read_text()) if ledger.exists() else {}
                operations = [json.loads(record.read_text()) for record in sorted((state / "operations").glob("*.json"))[-100:]]
                result[name] = {"jobs": data.get("upload_jobs", {}), "operations": operations, "background_ready": bool(cfg.get("ssh_key")), "transfers": [{"id": s.get("id"), "name": Path(s.get("source", "")).name, "state": s.get("state"), "bytes_total": s.get("bytes_total", 0), "bytes_sent": s.get("bytes_sent", 0), "bytes_per_second": s.get("bytes_per_second", 0)} for s in list(data.get("stages", {}).values())[-100:]]}
            return jsonify(backends=result)
        except (OSError, ValueError, KeyError):
            return jsonify(error="Remote backend configuration unavailable"), 503

    @bp.post("/api/remote-upload")
    def submit():
        try:
            data = request.get_json()
            if not isinstance(data, dict):
                raise ValueError("Expected JSON object")
            config = backends().get(data.get("backend"))
            if config is None:
                raise ValueError("Unknown backend")
            cfg = json.loads(config.read_text())
            if not cfg.get("ssh_key"):
                raise ValueError("Backend needs SSH-key authentication")
            action = data.get("action")
            if action not in {"execute", "tick"}:
                raise ValueError("Unknown action")
            arguments = []
            if action == "execute":
                source = Path(data["source"]).expanduser().resolve(strict=True)
                roots = [Path(p).expanduser().resolve() for p in cfg["source_roots"]]
                if not any(source.is_relative_to(root) and source != root for root in roots):
                    raise ValueError("Source outside approved roots")
                delay = float(data.get("return_after", 86400))
                if not math.isfinite(delay) or delay < 0:
                    raise ValueError("Invalid return interval")
                trackers = data.get("trackers")
                if not isinstance(trackers, list) or not trackers or any(not isinstance(t, str) or not t.replace("_", "").isalnum() for t in trackers):
                    raise ValueError("Select explicit trackers")
                options = shlex.split(str(data.get("arguments", "")))
                allowed = {"--edition", "-edition", "--imdb", "-imdb", "--tmdb", "-tmdb", "--tvdb", "-tvdb", "--tag", "-tag", "--year", "-year", "--category", "-category", "--type", "-type", "--source", "-source", "--resolution", "-resolution", "--screens", "-s", "--anon", "-anon", "--debug", "-debug", "--personalrelease", "-pr", "--unattended", "-ua"}
                forwarded = []
                index = 0
                while index < len(options):
                    token = options[index]
                    if token in {"-tk", "--trackers"}:
                        index += 2
                        continue
                    if token not in allowed:
                        raise ValueError("This option needs remote staging support")
                    forwarded.append(token)
                    index += 1
                    if token not in {"--anon", "-anon", "--debug", "-debug", "--personalrelease", "-pr", "--unattended", "-ua"}:
                        if index >= len(options) or options[index].startswith(("-", "/", "~")):
                            raise ValueError("Missing or unsupported remote option value")
                        forwarded.append(options[index])
                        index += 1
                arguments = [str(source), "--return-after", str(delay), "--arguments-json", json.dumps(forwarded), "--trackers", *trackers]
            state = Path(cfg["state_dir"]).expanduser() / "operations"
            state.mkdir(parents=True, exist_ok=True, mode=0o700)
            state.chmod(0o700)
            # A single reservation prevents unbounded subprocess/SSH floods.
            import fcntl
            with (state / "submit.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                if any(json.loads(p.read_text()).get("state") in {"queued", "running"} for p in state.glob("*.json")):
                    return jsonify(error="Backend operation already pending; inspect status before retrying"), 409
                id_ = uuid.uuid4().hex
                record = state / (id_ + ".json")
                atomic_write_text(record, json.dumps({"id": id_, "action": action, "state": "queued"}), default_mode=0o600)
                try:
                    subprocess.Popen([sys.executable, "-m", "src.remote_upload_worker", str(record), str(config.resolve()), action, *arguments], cwd=Path(__file__).resolve().parents[1], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                except OSError:
                    atomic_write_text(record, json.dumps({"id": id_, "action": action, "state": "failed"}), default_mode=0o600)
                    raise
            return jsonify(id=id_, state="queued"), 202
        except (ValueError, KeyError, TypeError, OSError):
            return jsonify(error="Invalid remote-upload request or unavailable configuration"), 400

    return bp

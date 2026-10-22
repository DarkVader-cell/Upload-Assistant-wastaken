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
from src.remote_transfer_control import control_transfer, transfer_status


class RequestValidationError(ValueError):
    """Safe, operator-facing validation error (never include config contents)."""


def remote_options(arguments):
    """Forward supported metadata only; never local paths or arbitrary positionals."""
    options = shlex.split(arguments)
    values = {"--edition", "-edition", "--imdb", "-imdb", "--tmdb", "-tmdb", "--tvdb", "-tvdb", "--tag", "-tag", "--year", "-year", "--category", "-category", "--type", "-type", "--source", "-source", "--resolution", "-resolution", "--screens", "-s"}
    flags = {"--anon", "-anon", "--debug", "-debug", "--personalrelease", "-pr", "--unattended", "-ua"}
    forwarded = []
    index = 0
    while index < len(options):
        token = options[index]
        if token in {"-tk", "--trackers"}:
            if index + 1 >= len(options):
                raise RequestValidationError("Missing tracker selection")
            index += 2
            continue
        if token not in values | flags:
            raise RequestValidationError("An upload option is not supported remotely; remove local-only options before retrying")
        forwarded.append(token)
        index += 1
        if token in values:
            if index >= len(options) or options[index].startswith(("-", "/", "~")):
                raise RequestValidationError("An upload option has a missing or local-only value")
            forwarded.append(options[index])
            index += 1
    return forwarded


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
                result[name] = {"jobs": data.get("upload_jobs", {}), "operations": operations, "background_ready": bool(cfg.get("ssh_key")), "transfers": [{"id": s.get("id"), "name": Path(s.get("source", "")).name, "state": s.get("state"), "protocol": s.get("protocol", "sftp"), "bytes_total": s.get("bytes_total", 0), "bytes_sent": s.get("bytes_sent", 0), "bytes_per_second": s.get("bytes_per_second", 0), **transfer_status(state, s)} for s in list(data.get("stages", {}).values())[-100:]]}
            return jsonify(backends=result)
        except (OSError, ValueError, KeyError):
            return jsonify(error="Remote backend configuration unavailable"), 503

    @bp.post("/api/remote-upload/control")
    def control():
        try:
            data = request.get_json()
            config = backends().get(data.get("backend"))
            if config is None:
                raise RequestValidationError("Unknown backend")
            cfg = json.loads(config.read_text())
            state = Path(cfg["state_dir"]).expanduser()
            ledger = json.loads((state / "ledger.json").read_text())
            record = ledger["stages"][data["stage"]]
            return jsonify(control_transfer(state, record, data["action"]))
        except (ValueError, KeyError, TypeError, AttributeError):
            return jsonify(error="No matching controllable transfer; legacy/completed jobs are not signalled"), 409
        except OSError:
            return jsonify(error="Transfer control unavailable; data retained"), 503

    @bp.post("/api/remote-upload")
    def submit():
        try:
            data = request.get_json()
            if not isinstance(data, dict):
                raise RequestValidationError("Expected JSON object")
            config = backends().get(data.get("backend"))
            if config is None:
                raise RequestValidationError("Select a configured remote backend on this UA host")
            cfg = json.loads(config.read_text())
            if not cfg.get("ssh_key"):
                raise RequestValidationError("Backend needs SSH-key authentication")
            action = data.get("action")
            if action not in {"execute", "tick", "discard"}:
                raise RequestValidationError("Unknown remote action")
            arguments = []
            if action == "execute":
                source = Path(data["source"]).expanduser().resolve(strict=True)
                roots = [Path(p).expanduser().resolve() for p in cfg["source_roots"]]
                if not any(source.is_relative_to(root) and source != root for root in roots):
                    raise RequestValidationError("Selected release is outside the backend's approved source folders")
                delay = float(data.get("return_after", 86400))
                if not math.isfinite(delay) or delay < 0:
                    raise RequestValidationError("Return interval must be a finite, nonnegative number")
                trackers = data.get("trackers")
                if not isinstance(trackers, list) or not trackers or any(not isinstance(t, str) or not t.replace("_", "").isalnum() for t in trackers):
                    raise RequestValidationError("Select explicit tracker identifiers")
                forwarded = remote_options(str(data.get("arguments", "")))
                arguments = [str(source), "--return-after", str(delay), "--arguments-json", json.dumps(forwarded), "--trackers", *trackers]
            if action == "discard":
                state_root = Path(cfg["state_dir"]).expanduser()
                record = json.loads((state_root / "ledger.json").read_text())["stages"][data["stage"]]
                if not transfer_status(state_root, record)["can_discard"]:
                    raise RequestValidationError("Stop the recorded transfer before removing partial data")
                arguments = [record["id"]]
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
        except RequestValidationError as error:
            return jsonify(error=str(error)), 400
        except PermissionError:
            return jsonify(error="UA cannot write remote job state; check service sandbox permissions"), 503
        except OSError:
            return jsonify(error="Remote source/configuration unavailable or job-state filesystem is read-only"), 503
        except (ValueError, KeyError, TypeError):
            return jsonify(error="Invalid remote request fields or backend configuration"), 400

    return bp

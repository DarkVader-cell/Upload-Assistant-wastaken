"""Authenticated, bounded local comparison rendering outside the upload queue."""
from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import threading
import zipfile
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, render_template, request, send_file

VIDEO_SUFFIXES = {".mkv", ".mp4", ".m2ts", ".avi", ".mov", ".vob", ".evo", ".mpg", ".mpeg"}


def validate_request(data: Any, resolve_path: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or not isinstance(data.get("sources"), list) or not 2 <= len(data["sources"]) <= 4:
        raise ValueError("Select between two and four video sources")
    sources = []
    for i, item in enumerate(data["sources"]):
        if not isinstance(item, dict):
            raise ValueError("Invalid source")
        path = Path(resolve_path(item.get("path"), require_exists=True))
        if not path.is_file() or path.suffix.lower() not in VIDEO_SUFFIXES:
            raise ValueError("Each source must be a supported video file inside the configured browse roots")
        label = str(item.get("label") or f"Source {i + 1}").strip()
        if not label or len(label) > 80 or any(ord(c) < 32 for c in label):
            raise ValueError("Source labels must contain 1-80 printable characters")
        offset = item.get("offset", 0)
        if type(offset) is not int or not 0 <= offset <= 1000000:
            raise ValueError("Frame offsets must be integers between 0 and 1000000")
        tonemap = item.get("tonemap", "auto")
        if tonemap not in {"none", "auto", "hdr", "hdr10plus", "dovi"}:
            raise ValueError("Invalid tone-mapping mode")
        sources.append({"path": str(path), "label": label, "offset": offset, "tonemap": tonemap})
    count = data.get("count", 4)
    if type(count) is not int or not 1 <= count <= 8:
        raise ValueError("Choose between one and eight comparison frames")
    frames = data.get("frames", [])
    if not isinstance(frames, list) or len(frames) > 8 or any(type(x) is not int or not 0 <= x <= 10000000 for x in frames):
        raise ValueError("Frames must contain at most eight nonnegative integers")
    return {"sources": sources, "count": count, "frames": frames}


def create_comparison_blueprint(*, authenticated: Any, csrf_valid: Any, same_origin: Any,
                                csrf_token: Any, resolve_path: Any, state_root: Path, code_root: Path) -> Blueprint:
    blueprint = Blueprint("comparisons", __name__)
    root = state_root / "tmp" / "comparisons"
    lock = threading.Lock()
    jobs: dict[str, dict[str, Any]] = {}
    active = threading.BoundedSemaphore(1)

    def runtime() -> tuple[Path, Path]:
        python = Path(os.environ.get("UA_COMPARISON_PYTHON", "/nonexistent"))
        script = Path(os.environ.get("UA_COMPARISON_SCRIPT", "/nonexistent"))
        if not python.is_file() or not os.access(python, os.X_OK) or not script.is_file():
            raise ValueError("Comparison runtime is not installed on this instance")
        return python, script

    def run_job(job_id: str, python: Path, script: Path) -> None:
        directory = root / job_id
        try:
            with lock:
                jobs[job_id]["status"] = "running"
            with (directory / "render.log").open("wb") as log:
                subprocess.run([str(python), str(code_root / "scripts" / "render-comparisons.py"), str(directory / "job.json"), str(script)],  # noqa: S603 - operator-installed interpreter, fixed argv, no shell.
                               stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, timeout=1800, check=True,
                               env={**os.environ, "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "1"})
            manifest = json.loads((directory / "manifest.json").read_text())
            files = [x["name"] for x in manifest["files"]]
            if not files or len(files) > 32 or any(re.fullmatch(r"\d{3}-\d{2}-[A-Za-z0-9._-]{1,48}\.png", n) is None for n in files):
                raise ValueError("Renderer returned invalid output")
            with zipfile.ZipFile(directory / "comparisons.zip", "w", compression=zipfile.ZIP_STORED) as archive:
                for name in files:
                    path = directory / name
                    if path.is_symlink() or not path.is_file():
                        raise ValueError("Missing comparison output")
                    archive.write(path, name)
                # Keep input paths confined to private job.json, not the shared ZIP.
                public_manifest = {"frames": manifest["frames"], "sources": [s["label"] for s in manifest["sources"]], "files": manifest["files"]}
                archive.writestr("manifest.json", json.dumps(public_manifest, indent=2))
            with lock:
                jobs[job_id].update(status="completed", files=files)
        except Exception:
            with lock:
                jobs[job_id].update(status="failed", error="Rendering failed. Check the private render.log on the server; verify source offsets, tone mapping and runtime plugins.")
        finally:
            active.release()

    @blueprint.before_request
    def secure():
        if not authenticated():
            return jsonify(success=False, error="Web session authentication required"), 401
        if request.method == "POST" and (not csrf_valid() or not same_origin()):
            return jsonify(success=False, error="CSRF/Origin validation failed"), 403
        return None

    @blueprint.get("/comparisons")
    def page():
        try:
            runtime()
            ready = True
        except ValueError:
            ready = False
        return render_template("comparisons.html", csrf_token=csrf_token(), runtime_ready=ready)

    @blueprint.post("/api/comparisons")
    def create():
        try:
            python, script = runtime()
            config = validate_request(request.get_json(silent=True), resolve_path)
        except (ValueError, TypeError, OSError):
            return jsonify(success=False, error="Check source paths, labels, frame settings and installed comparison runtime"), 400
        if not active.acquire(blocking=False):
            return jsonify(success=False, error="A comparison is already rendering. Try again after it finishes."), 409
        try:
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            job_id = secrets.token_hex(16)
            directory = root / job_id
            directory.mkdir(mode=0o700)
            with (directory / "job.json").open("x", encoding="utf-8") as handle:
                Path(handle.name).chmod(0o600)
                json.dump(config, handle)
            with lock:
                # Bounded in-memory history; disk artifacts stay available for manual cleanup.
                if len(jobs) >= 30:
                    for old in list(jobs)[:-20]:
                        if jobs[old]["status"] not in {"queued", "running"}:
                            jobs.pop(old)
                jobs[job_id] = {"status": "queued", "files": []}
            threading.Thread(target=run_job, args=(job_id, python, script), daemon=True).start()
            return jsonify(success=True, id=job_id), 202
        except Exception:
            active.release()
            return jsonify(success=False, error="Unable to create comparison job"), 500

    @blueprint.get("/api/comparisons/<job_id>")
    def status(job_id: str):
        with lock:
            job = jobs.get(job_id)
            return (jsonify(success=True, id=job_id, **job) if job else (jsonify(success=False, error="Job unavailable (server may have restarted)"), 404))

    @blueprint.get("/api/comparisons/<job_id>/<filename>")
    def output(job_id: str, filename: str):
        with lock:
            job = jobs.get(job_id)
            allowed = job and job["status"] == "completed" and (filename == "comparisons.zip" or filename in job["files"])
        if not allowed:
            return jsonify(success=False, error="Output unavailable"), 404
        return send_file(root / job_id / filename, as_attachment=filename.endswith(".zip"), max_age=0)

    return blueprint

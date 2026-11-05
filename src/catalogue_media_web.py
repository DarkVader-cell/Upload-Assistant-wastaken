"""Authenticated existing-file tools. No payload download or automatic processing."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import stat
import sys
import time
from contextlib import suppress
from pathlib import Path

import httpx
from aiohttp import web

from src.catalogue_media import MediaError, _identify, _owned_path, _run, planned_output
from src.catalogue_rate import APIPacer
from src.catalogue_runner import API, load_settings, locked_state
from src.media_selection import FONT_MIMES, cleanup_options, readable_tags
from src.media_template import DEFAULT_TEMPLATE, NAMING_KEYS, validate_options

ROOT = Path(__file__).resolve().parents[1]


def filename_identity(name):
    """Filename is a hint, never authoritative identity or a full external query."""
    if not isinstance(name, str) or len(name) > 500 or re.search(r"\bS\d{1,2}E\d{1,3}\b", name, re.I):
        raise ValueError("Movie filenames only; enter a canonical movie title/year")
    stem = Path(name).stem
    matches = list(re.finditer(r"(?<!\d)((?:19|20)\d{2})(?!\d)", stem))
    year = int(matches[-1][1]) if matches else None
    title = stem[: matches[-1].start()] if matches else re.split(r"\b(?:480p|720p|1080p|2160p|WEB|BluRay)\b", stem, maxsplit=1, flags=re.I)[0]
    title = re.sub(r"[._]+", " ", title).strip(" -[]()")
    title = re.sub(r"\s+", " ", title)
    if not title or len(title) > 200:
        raise ValueError("Enter a canonical movie title")
    return {"title": title, "year": year}


def normalized(value):
    return "".join(character for character in str(value).casefold() if character.isalnum())


def fingerprint(path):
    info = path.stat()
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink]


def existing_parent(path):
    while not path.exists():
        path = path.parent
    return path


class MediaUI:
    def __init__(self, dashboard):
        self.dashboard = dashboard
        self.matches = {}
        self.plans = {}
        self.job = None
        self.child = None
        self.task = None
        self.lease = None
        self.operation = asyncio.Lock()

    @property
    def busy(self):
        return self.task is not None and not self.task.done()

    def roots(self):
        paths = self.dashboard.config().get("media_roots", [])
        if not isinstance(paths, list) or len(paths) > 16:
            raise ValueError("Media roots require private administrator configuration")
        roots = []
        for value in paths:
            path = Path(value).expanduser().absolute()
            if not path.is_absolute() or path.resolve() != path or path in {Path("/"), Path.home()} or any(part.startswith(".") for part in path.parts):
                raise ValueError("Media roots must be explicit canonical media folders")
            info = path.stat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
                raise ValueError("Media root is not an owned non-shared directory")
            roots.append(path)
        return roots

    def path(self, root_id, relative, directory=False, allow_new=False):
        roots = self.roots()
        if type(root_id) is not int or not 0 <= root_id < len(roots) or not isinstance(relative, str) or len(relative) > 2000:
            raise ValueError("Invalid media folder selection")
        name = Path(relative)
        if name.is_absolute() or ".." in name.parts or any(part.startswith(".") for part in name.parts):
            raise ValueError("Only visible paths within the selected root are allowed")
        try:
            path = _owned_path(roots[root_id], roots[root_id] / name, exists=not allow_new)
        except MediaError:
            raise ValueError("Path is not an owned non-symlink media target") from None
        if path.exists():
            if directory and not path.is_dir():
                raise ValueError("Select a directory")
            if not directory and (not path.is_file() or path.suffix.lower() not in {".mkv", ".mp4"}):
                raise ValueError("Select a regular MKV or MP4")
        elif not allow_new:
            raise ValueError("Path does not exist")
        return path

    def archive(self):
        path = (
            Path(self.dashboard.config().get("media_tool_archive", str(Path.home() / "apps/ua-catalogue/standalone/current/media-release.pyz")))
            .expanduser()
            .resolve(strict=True)
        )
        info = path.stat()
        if not path.is_file() or info.st_uid != os.getuid() or info.st_mode & 0o022 or info.st_size > 2 * 1024 * 1024:
            raise ValueError("Standalone archive is unavailable")
        receipt = json.loads(path.with_name("VALIDATION.json").read_text())
        if hashlib.sha256(path.read_bytes()).hexdigest() != receipt.get("sha256"):
            raise ValueError("Standalone archive failed integrity validation")
        return path

    def preferences(self, body=None):
        path = Path(self.dashboard.config()["state_dir"]) / "media-preferences.json"
        if body is None:
            if not path.exists():
                return validate_options()
            if path.is_symlink() or path.stat().st_size > 10000:
                raise ValueError("Invalid media preferences")
            return validate_options(**json.loads(path.read_text()))
        options = validate_options(
            body.get("group", ""), body.get("template", DEFAULT_TEMPLATE), body.get("tags", {}), **{key: body[key] for key in NAMING_KEYS if key in body}
        )
        from src.catalogue_web import atomic_json

        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_json(path, options)
        return options

    def inspect(self, body):
        path = self.path(body.get("root"), body.get("path"))
        report = _identify(path)
        props = report.get("container", {}).get("properties", {})
        return {
            "writing_application": props.get("writing_application", "unknown"),
            "muxing_application": props.get("muxing_application", "unknown"),
            "container_title": props.get("title", ""),
            "mux_date": props.get("date_utc", props.get("date_local", "")),
            "tags": readable_tags(_run(["mkvextract", str(path), "tags"]).decode("utf-8")) if path.suffix.lower() == ".mkv" else [],
            "attachments": [
                {"id": str(a["id"]), "name": a.get("file_name", ""), "type": a.get("content_type", ""), "size": a.get("size"), "font": a.get("content_type", "") in FONT_MIMES}
                for a in report.get("attachments", [])
            ],
            "output_application": _run(["mkvmerge", "--version"]).decode("utf-8").strip()[:300],
            "tracks": [
                {
                    "id": track["id"],
                    "type": track.get("type"),
                    "codec": track.get("codec", ""),
                    "default": bool(track.get("properties", {}).get("default_track")),
                    "forced": bool(track.get("properties", {}).get("forced_track")),
                    "hearing_impaired": bool(track.get("properties", {}).get("hearing_impaired", track.get("properties", {}).get("flag_hearing_impaired", False))),
                    "commentary": bool(track.get("properties", {}).get("commentary", track.get("properties", {}).get("flag_commentary", False))),
                    "name": track.get("properties", {}).get("track_name", ""),
                    "language": track.get("properties", {}).get("language_ietf", track.get("properties", {}).get("language")),
                }
                for track in report.get("tracks", [])
            ],
        }

    def status(self):
        try:
            self.archive()
            downloadable = True
        except (OSError, ValueError):
            downloadable = False
        return {
            "roots": [{"id": index, "path": str(path)} for index, path in enumerate(self.roots())],
            "download_available": downloadable,
            "busy": self.busy,
            "job": self.job,
            "movie_only": True,
            "preferences": self.preferences(),
            "batch_limit": 25,
            "privacy_limit": "Container metadata cleanup cannot remove forensic watermarks or in-stream identifiers; Fonts and unselected metadata are preserved; review selected fields for PII.",
        }

    def files(self, body):
        directory = self.path(body.get("root"), body.get("path", ""), directory=True)
        entries = []
        with os.scandir(directory) as listing:
            for index, entry in enumerate(listing):
                if index >= 5000:
                    raise ValueError("Directory too large; select a narrower folder")
                if entry.name.startswith(".") or entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False) or (entry.is_file(follow_symlinks=False) and Path(entry.name).suffix.lower() in {".mkv", ".mp4"}):
                    entries.append({"name": entry.name, "directory": entry.is_dir(follow_symlinks=False)})
        entries.sort(key=lambda item: (not item["directory"], item["name"].casefold()))
        return {"entries": entries[:200], "truncated": len(entries) > 200}

    def tmdb(self, path, parameters=None):
        cfg, ua = load_settings(self.dashboard.config_path)
        key = ua.get("DEFAULT", {}).get("tmdb_api")
        if not key:
            raise ValueError("Existing UA TMDB key is not configured")
        with httpx.Client(timeout=25, trust_env=False, follow_redirects=False) as client:
            api = API(
                client, pacer=APIPacer(Path(cfg["state_dir"]) / "api-rate.sqlite3", cfg.get("tracker_request_interval_seconds", 10), cfg.get("tracker_daily_api_limit", 200))
            )
            return api.request("GET", "https://api.themoviedb.org/3/" + path, params={**(parameters or {}), "api_key": key})

    def details(self, tmdb):
        if type(tmdb) is not int or tmdb < 1:
            raise ValueError("Invalid TMDB movie identifier")
        data = self.tmdb(f"movie/{tmdb}")
        imdb = data.get("imdb_id")
        title = data.get("title")
        date = data.get("release_date", "")
        if (
            data.get("id") != tmdb
            or not isinstance(imdb, str)
            or not re.fullmatch(r"tt[0-9]{7,10}", imdb)
            or not isinstance(title, str)
            or not title
            or not re.match(r"^(?:19|20)[0-9]{2}-", date)
        ):
            raise ValueError("Movie identity is incomplete; no processing permitted")
        return {"tmdb": tmdb, "imdb": imdb, "title": title[:300], "year": int(date[:4]), "original_language": data.get("original_language")}

    def prune(self):
        for mapping in (self.matches, self.plans):
            for key in list(mapping):
                if mapping[key]["expires"] < time.monotonic():
                    del mapping[key]
            while len(mapping) > 100:
                del mapping[next(iter(mapping))]

    def match(self, body, owner):
        self.prune()
        source = self.path(body.get("root"), body.get("path"))
        hint = filename_identity(source.name)
        title = body.get("title") or hint["title"]
        year = body.get("year") or hint["year"]
        embedded_imdb = re.search(r"(?<![A-Za-z0-9])(tt[0-9]{7,10})(?![0-9])", source.name, re.I)
        embedded_tmdb = re.search(r"(?:^|[. _-])tmdb[-_. ]([0-9]+)(?![0-9])", source.name, re.I)
        imdb = body.get("imdb") or (embedded_imdb[1].lower() if embedded_imdb else None)
        tmdb = body.get("tmdb") or (int(embedded_tmdb[1]) if embedded_tmdb else None)
        if not isinstance(title, str) or not 1 <= len(title) <= 200 or (year is not None and (type(year) is not int or not 1870 <= year <= 2100)):
            raise ValueError("Provide a canonical title and release year")
        request_key = repr((body.get("root"), body.get("path"), title, year, imdb, tmdb))
        snapshot = fingerprint(source)
        for cached in self.matches.values():
            if cached["owner"] == owner and cached.get("request_key") == request_key and cached["fingerprint"] == snapshot:
                return dict(cached["response"])
        if imdb:
            if not isinstance(imdb, str) or not re.fullmatch(r"tt[0-9]{7,10}", imdb):
                raise ValueError("Invalid IMDb ID")
            data = self.tmdb(f"find/{imdb}", {"external_source": "imdb_id"})
            rows = data.get("movie_results", [])
        elif tmdb:
            detail = self.details(tmdb)
            rows = [{"id": tmdb, "title": detail["title"], "release_date": str(detail["year"])}]
        else:
            data = self.tmdb("search/movie", {"query": title, "include_adult": "false", **({"year": year} if year else {})})
            rows = data.get("results", [])
        if not isinstance(rows, list):
            raise ValueError("TMDB search response changed")
        candidates = [
            {"tmdb": row["id"], "title": row.get("title", "")[:300], "year": str(row.get("release_date", ""))[:4], "original_title": row.get("original_title", "")[:300]}
            for row in rows[:8]
            if isinstance(row, dict) and type(row.get("id")) is int and row["id"] > 0
        ]
        exact = [
            row for row in candidates if year is not None and row["year"] == str(year) and normalized(title) in {normalized(row["title"]), normalized(row["original_title"])}
        ]
        selected = self.details(exact[0]["tmdb"]) if len(exact) == 1 else None
        if selected and imdb and selected["imdb"] != imdb:
            raise ValueError("Conflicting IMDb/TMDB identity; manual review required")
        token = secrets.token_urlsafe(24)
        self.matches[token] = {
            "owner": owner,
            "expires": time.monotonic() + 900,
            "root": body["root"],
            "path": body["path"],
            "fingerprint": snapshot,
            "request_key": request_key,
            "candidates": candidates,
            "selected": selected,
            "requested_imdb": imdb,
        }
        response = {"match_id": token, "hint": hint, "candidates": candidates, "selected": selected, "requested_imdb": imdb, "requires_review": selected is None}
        self.matches[token]["response"] = response
        return response

    def preview(self, body, owner):
        self.prune()
        matched = self.matches.get(body.get("match_id"))
        if not matched or matched["owner"] != owner:
            raise ValueError("Movie match expired; match again")
        source = self.path(matched["root"], matched["path"])
        if fingerprint(source) != matched["fingerprint"]:
            raise ValueError("Input changed; match again")
        selected_id = body.get("tmdb")
        if type(selected_id) is not int or selected_id not in {candidate["tmdb"] for candidate in matched["candidates"]}:
            raise ValueError("Select a returned movie identity")
        identity = matched["selected"] if matched["selected"] and matched["selected"]["tmdb"] == selected_id else self.details(selected_id)
        if matched.get("requested_imdb") and identity["imdb"] != matched["requested_imdb"]:
            raise ValueError("Conflicting IMDb/TMDB identity; no processing permitted")
        provider = body.get("provider")
        audio_index = body.get("audio_index")
        linked = body.get("allow_linked_input") is True
        if audio_index is not None and (type(audio_index) is not int or audio_index < 0):
            raise ValueError("Invalid audio index")
        if source.stat().st_nlink > 1 and not linked:
            raise ValueError("Hardlinked input requires explicit read-only consent")
        destination = self.path(body.get("output_root"), body.get("output_path", ""), directory=True, allow_new=True)
        group = body.get("group", "Kitsune")
        template = body.get("template")
        tags = validate_options(group, template if template is not None else DEFAULT_TEMPLATE, body.get("tags", {}))["tags"].copy()
        if body.get("tag_group_name") is True and group:
            tags.setdefault("GROUP", group)
        naming_options = validate_options(group, template or DEFAULT_TEMPLATE, {}, **{key: body[key] for key in NAMING_KEYS if key in body})
        naming = planned_output(
            source,
            identity["title"],
            identity["year"],
            provider,
            group=group,
            audio_index=audio_index,
            template=template,
            original_language=identity.get("original_language"),
            naming_options=naming_options,
        )
        name = naming["filename"]
        if body.get("tag_group_name") is True:
            selected_group = naming["context"].get("tag", group)
            if selected_group:
                tags["GROUP"] = selected_group
            else:
                tags.pop("GROUP", None)
        if naming["folder"]:
            destination = self.path(body.get("output_root"), str(Path(body.get("output_path", "")) / naming["folder"]), directory=True, allow_new=True)
        if (destination / name).exists():
            raise ValueError("Destination exists; never overwrite")
        subtitles = body.get("subtitle_languages", {})
        if (
            not isinstance(subtitles, dict)
            or len(subtitles) > 30
            or any(not isinstance(key, str) or not key.isdigit() or not isinstance(value, str) or len(value) > 20 for key, value in subtitles.items())
        ):
            raise ValueError("Invalid subtitle corrections")
        token = secrets.token_urlsafe(24)
        plan = {
            **matched,
            "identity": identity,
            "cleanup": cleanup_options(body.get("cleanup", {})),
            "group": group,
            "template": template,
            "tags": tags,
            "provider": provider,
            "audio_index": audio_index,
            "linked": linked,
            "subtitles": subtitles,
            "output_root": body["output_root"],
            "output_path": str(destination.relative_to(self.roots()[body["output_root"]])),
            "name": name,
        }
        self.plans[token] = plan
        return {
            "plan_id": token,
            "tags": {"IMDB": identity["imdb"], "TMDB": str(identity["tmdb"]), **tags},
            "writing_application": "Actual mkvmerge; verified after remux",
            "metadata_edits": cleanup_options(body.get("cleanup", {})),
            "identity": identity,
            "filename": name,
            "original_retained": True,
            "linked_input": source.stat().st_nlink > 1,
            "privacy": "Remove only selected metadata plus CardinalDL branding; preserve fonts/unselected fields, use real mkvmerge, verify audio/video hashes. Originals retained. Preserved fields are not certified PII-free.",
            "output_folder": str(destination),
        }

    async def start(self, body, owner):
        self.prune()
        plan = self.plans.get(body.get("plan_id"))
        if not plan or plan["owner"] != owner:
            raise web.HTTPBadRequest(text="Create a current preview before processing")
        if self.busy or self.dashboard.busy:
            raise web.HTTPConflict(text="Another media/catalogue job is active")
        source = self.path(plan["root"], plan["path"])
        if fingerprint(source) != plan["fingerprint"]:
            raise web.HTTPConflict(text="Input changed; preview again")
        destination = self.path(plan["output_root"], plan["output_path"], directory=True, allow_new=True)
        if shutil.disk_usage(existing_parent(destination)).free < source.stat().st_size * 1.1:
            raise web.HTTPConflict(text="Not enough free space to retain the original and create a verified copy")
        cfg = self.dashboard.config()
        lease = locked_state(Path(cfg["state_dir"]))
        lease.__enter__()
        self.lease = lease
        self.plans.pop(body["plan_id"])
        self.job = {"status": "running", "filename": plan["name"], "original_retained": True}
        self.task = asyncio.create_task(self.execute(plan))
        return {"started": True}

    async def start_batch(self, body, owner):
        self.prune()
        ids = body.get("plan_ids")
        if not isinstance(ids, list) or not 1 <= len(ids) <= 25 or any(not isinstance(value, str) for value in ids) or len(set(ids)) != len(ids):
            raise web.HTTPBadRequest(text="Select 1-25 unique current previews before processing")
        if self.busy or self.dashboard.busy:
            raise web.HTTPConflict(text="Another media/catalogue job is active")
        plans = []
        outputs = set()
        inputs = set()
        disks = {}
        for token in ids:
            plan = self.plans.get(token)
            if not plan or plan["owner"] != owner:
                raise web.HTTPBadRequest(text="Batch preview expired; preview again")
            source = self.path(plan["root"], plan["path"])
            snap = fingerprint(source)
            if snap != plan["fingerprint"] or tuple(snap[:2]) in inputs:
                raise web.HTTPConflict(text="Changed or duplicate source payload")
            inputs.add(tuple(snap[:2]))
            destination = self.path(plan["output_root"], plan["output_path"], directory=True, allow_new=True)
            target = str(destination / plan["name"]).casefold()
            if target in outputs or (destination / plan["name"]).exists():
                raise web.HTTPConflict(text="Batch output collision; resolve before processing")
            outputs.add(target)
            parent = existing_parent(destination)
            device = parent.stat().st_dev
            used, free = disks.get(device, (0, shutil.disk_usage(parent).free))
            disks[device] = (used + source.stat().st_size * 1.1, free)
            plans.append(plan)
        if any(used > free for used, free in disks.values()):
            raise web.HTTPConflict(text="Insufficient space for all verified copies")
        lease = locked_state(Path(self.dashboard.config()["state_dir"]))
        lease.__enter__()
        self.lease = lease
        for token in ids:
            self.plans.pop(token)
        self.job = {"status": "running", "total": len(plans), "completed": 0, "results": [], "original_retained": True}
        self.task = asyncio.create_task(self.execute_batch(plans))
        return {"started": True, "total": len(plans)}

    async def execute_batch(self, plans):
        results = []
        try:
            for plan in plans:
                self.job = {"status": "running", "filename": plan["name"], "total": len(plans), "completed": len(results), "results": list(results), "original_retained": True}
                await self.execute(plan, release=False)
                result = {"filename": plan["name"], **self.job}
                result.pop("results", None)
                results.append(result)
                if result["status"] != "succeeded":
                    break
            self.job = {
                "status": "succeeded" if len(results) == len(plans) and all(r["status"] == "succeeded" for r in results) else "failed",
                "total": len(plans),
                "completed": sum(r["status"] == "succeeded" for r in results),
                "results": results,
                "original_retained": True,
            }
        except asyncio.CancelledError:
            self.job = {
                "status": "cancelled",
                "total": len(plans),
                "completed": sum(r["status"] == "succeeded" for r in results),
                "results": results,
                "original_retained": True,
            }
            raise
        finally:
            await self.stop_child()
            self.child = None
            self.release_lease()

    async def execute(self, plan, release=True):
        try:
            source = self.path(plan["root"], plan["path"])
            if fingerprint(source) != plan["fingerprint"]:
                raise ValueError("Input changed")
            destination = self.path(plan["output_root"], plan["output_path"], directory=True, allow_new=True)
            if not destination.exists():
                destination.mkdir(mode=0o700, parents=True)
            destination = self.path(plan["output_root"], plan["output_path"], directory=True)
            arguments = [
                sys.executable,
                str(ROOT / "tools/media-release.py"),
                str(source),
                "--root",
                str(self.roots()[plan["root"]]),
                "--output",
                str(destination / plan["name"]),
                "--output-root",
                str(self.roots()[plan["output_root"]]),
                "--title",
                plan["identity"]["title"],
                "--year",
                str(plan["identity"]["year"]),
                "--provider",
                plan["provider"],
                "--imdb",
                plan["identity"]["imdb"],
                "--tmdb",
                str(plan["identity"]["tmdb"]),
                "--execute",
            ]
            arguments.extend(["--group", plan.get("group", "Kitsune"), "--tags-json", json.dumps(plan.get("tags", {})), "--cleanup-json", json.dumps(plan.get("cleanup", {}))])
            if plan.get("template") is not None:
                arguments.extend(["--template", plan["template"]])
            if plan["linked"]:
                arguments.append("--allow-linked-input")
            if plan["audio_index"] is not None:
                arguments.extend(["--audio-index", str(plan["audio_index"])])
            for track, language in plan["subtitles"].items():
                arguments.extend(["--subtitle-language", f"{track}={language}"])
            self.child = await asyncio.create_subprocess_exec(
                *arguments, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, start_new_session=True
            )
            output, _ = await asyncio.wait_for(self.child.communicate(), timeout=7200)
            if len(output) > 65536:
                raise ValueError("Oversized report")
            report = json.loads(output)
            if (
                self.child.returncode != 0
                or report.get("executed") is not True
                or report.get("metadata_selection_verified") is not True
                or report.get("audio_video_hashes_verified") is not True
                or report.get("original_retained") is not True
                or Path(report.get("output", "")).name != plan["name"]
            ):
                raise ValueError("Verification failed")
            completed = self.path(plan["output_root"], str(Path(plan["output_path"]) / plan["name"]))
            if completed.stat().st_size != report.get("bytes") or completed.stat().st_size < 1 or fingerprint(source) != plan["fingerprint"]:
                raise ValueError("Published output or original verification failed")
            self.job = {"status": "succeeded", "filename": plan["name"], "original_retained": True, "privacy_verified": True, "packet_hashes_verified": True}
        except asyncio.CancelledError:
            self.job = {"status": "cancelled", "original_retained": True}
            raise
        except (OSError, ValueError, TypeError, TimeoutError):
            self.job = {"status": "failed", "reason": "Media verification failed or job timed out; original retained", "original_retained": True}
        finally:
            await self.stop_child()
            self.child = None
            if release:
                self.release_lease()

    def release_lease(self):
        if self.lease is not None:
            lease, self.lease = self.lease, None
            lease.__exit__(None, None, None)

    async def stop_child(self):
        if self.child and self.child.returncode is None:
            try:
                os.killpg(self.child.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
            try:
                await asyncio.wait_for(self.child.wait(), timeout=10)
            except TimeoutError:
                with suppress(ProcessLookupError):
                    os.killpg(self.child.pid, signal.SIGKILL)
                await self.child.wait()

    async def cancel(self):
        if self.busy:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            finally:
                await self.stop_child()
                self.release_lease()
                if self.job and self.job.get("status") == "running":
                    self.job = {"status": "cancelled", "original_retained": True}


def install_media_routes(app, dashboard, cookie, object_body):
    manager = MediaUI(dashboard)
    dashboard.media = manager

    async def status(request):
        value = await asyncio.to_thread(manager.status)
        value["csrf"] = dashboard.sessions[request.cookies[cookie]][1]
        return web.json_response(value)

    async def download(_request):
        path = await asyncio.to_thread(manager.archive)
        response = web.FileResponse(path)
        response.headers["Content-Disposition"] = 'attachment; filename="media-release.pyz"'
        response.content_type = "application/octet-stream"
        return response

    async def operation(request):
        if manager.operation.locked():
            raise web.HTTPConflict(text="Another media metadata request is active")
        body = await object_body(request)
        name = request.match_info["operation"]
        owner = request.cookies.get(cookie, "")
        async with manager.operation:
            try:
                if name == "files":
                    result = await asyncio.to_thread(manager.files, body)
                elif name == "preferences":
                    result = await asyncio.to_thread(manager.preferences, body)
                elif name == "inspect":
                    result = await asyncio.to_thread(manager.inspect, body)
                elif name == "batch-process":
                    result = await manager.start_batch(body, owner)
                elif name == "match":
                    result = await asyncio.to_thread(manager.match, body, owner)
                elif name == "preview":
                    result = await asyncio.to_thread(manager.preview, body, owner)
                elif name == "process":
                    result = await manager.start(body, owner)
                elif name == "cancel":
                    await manager.cancel()
                    result = {"cancelled": True}
                else:
                    raise web.HTTPNotFound()
                return web.json_response(result)
            except (MediaError, ValueError) as error:
                raise web.HTTPBadRequest(text=str(error)[:240] or "Media request refused") from None

    app.router.add_get("/api/media", status)
    app.router.add_get("/api/media/tool", download)
    app.router.add_post("/api/media/{operation:files|match|preview|process|cancel|preferences|inspect|batch-process}", operation)
    return manager

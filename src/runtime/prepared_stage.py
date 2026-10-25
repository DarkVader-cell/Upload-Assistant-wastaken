"""Source/option-bound preparation checkpoints, never cached upload permission."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import time
from functools import lru_cache
from pathlib import Path

from src.console import logger
from src.meta import Meta
from src.runtime.state import default_config
from src.temp_paths import release_temp_dir

_PRIVATE = ("password", "passkey", "api_key", "api_token", "cookie", "credential", "secret", "session", "token", "authorization", "authkey", "download_url")
_TRANSIENT = {"tracker_status", "initial_dupes", "we_are_uploading", "trackers", "trackers_remove", "delete_meta", "delete_tmp", "queue", "queue_file", "confirm_not_uploaded", "we_checked_them_all", "skip_trackers", "skip_uploading", "dupe", "force_upload", "modq", "draft", "unattended", "unattended_confirm", "remove_trackers", "client", "no_seed", "skipping", "ptp_groupid", "ptp_torrent_id"}


def _clean(value, *, losses=None):
    if isinstance(value, dict):
        return {str(k): _clean(v, losses=losses) for k, v in value.items() if not any(p in str(k).casefold() for p in _PRIVATE)}
    if isinstance(value, (list, tuple)):
        return [_clean(v, losses=losses) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_clean(v, losses=losses) for v in value), key=str)
    if isinstance(value, str) and any(part + "=" in value.casefold() for part in _PRIVATE):
        if losses is not None:
            losses.append(True)
        return None
    return value


def _source_stamp(path: Path):
    if path.is_symlink() or not path.exists():
        return None
    if path.is_file():
        companions = [p for p in path.parent.iterdir() if p.name.casefold().startswith(path.stem.casefold()) and p.suffix.casefold() in {".srt", ".sub", ".idx", ".ssa", ".ass", ".vtt", ".nfo", ".xml"}]
        paths = sorted({path, *companions})
    else:
        paths = sorted(path.rglob("*"))
    result = []
    for item in paths:
        if item.is_symlink():
            return None
        if item.is_file():
            s = item.stat()
            result.append([str(item.resolve()), s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns])
    return result or None


@lru_cache(maxsize=1)
def _preparation_version():
    digest = hashlib.sha256(b"prepared-stage-v1")
    root = Path(__file__).resolve().parents[1]
    for relative in ("prep.py", "prep_helpers.py", "meta.py", "slot_rules/profile.py", "runtime/prepared_stage.py"):
        try:
            digest.update((root / relative).read_bytes())
        except OSError:
            continue
    return digest.hexdigest()


class PreparationSourceChangedError(RuntimeError):
    """Existing per-release artifacts must not silently switch to new input."""


class PreparedStage:
    def __init__(self, meta, config):
        self.source = Path(str(meta.path or ""))
        self.enabled = bool(meta.path) and not getattr(meta, "no_metadata_cache", False) and default_config(config).get("stage_checkpoints_enabled", True) is not False
        self.enabled = self.enabled and (meta.category in {"MOVIE", "TV"} or (not meta.category and self.source.is_file()))
        self.path = release_temp_dir(meta.base_dir, meta.uuid or self.source.name) / "prepared_stage.json"
        self.initial = _source_stamp(self.source) if self.enabled else None
        if not self.enabled:
            self.key, self.force = "", False
            return
        controls = dict(meta.to_dict())
        for key in ("uuid", "queue", "queue_file", "delete_meta", "delete_tmp", "confirm_not_uploaded"):
            controls.pop(key, None)
        identity = _clean({"preparation_version": _preparation_version(), "controls": controls, "defaults": dict(default_config(config)),
                           "default_trackers": config.get("TRACKERS", {}).get("default_trackers") if not meta.trackers else None})
        self.key = hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()
        self.force = bool(meta.delete_meta or meta.delete_tmp or getattr(meta, "no_metadata_cache", False))

    def load(self):
        if not self.enabled or not self.initial:
            return None
        try:
            row = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(row, dict):
                return None
            data = row.get("meta")
            if row.get("version") == 1 and row.get("source") != self.initial:
                raise PreparationSourceChangedError("Source/companion fingerprint changed since preparation (possibly metadata-only). Do not reuse this release's old screenshots/torrent. Choose a fresh work directory, or --delete-tmp only if no active run uses it and its temporary tree does not overlap the payload. This check did not alter the original payload.")
            if self.force or row.get('reusable') is False or row.get("version") != 1 or row.get("key") != self.key:
                return None
            if not 0 <= time.time() - row["saved"] <= 86400 or not isinstance(data, dict):
                return None
            if data.get("category") not in {"MOVIE", "TV"} or data.get("is_disc"):
                return None
            if not (self.path.parent / "MEDIAINFO.txt").is_file() or (self.path.parent / "MEDIAINFO.txt").stat().st_size == 0:
                return None
            if not data.get("filelist") or not all(Path(p).is_file() for p in data["filelist"]):
                return None
            if row.get("files") != [_source_stamp(Path(p)) for p in data["filelist"]]:
                return None
            return data
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def save(self, meta):
        if not self.enabled or not self.initial or meta.category not in {"MOVIE", "TV"} or meta.is_disc or meta.hdb_offer or meta.hdb_manual:
            return
        if _source_stamp(self.source) != self.initial:
            return
        data = {}
        for key, value in meta.to_dict().items():
            if key in _TRANSIENT or key.startswith("_") or ("_" in key and key.split("_", 1)[0].isupper()):
                continue
            if any(part in key.casefold() for part in ("trump", "protected", "_status", "_title_releases", "_search_failed", "_report_candidates", "_matched_episode")):
                continue
            data[key] = value
        losses = []
        cleaned = _clean(data, losses=losses)
        row = {"version": 1, "key": self.key, "source": self.initial, "saved": time.time(), "meta": cleaned, "reusable": not losses, "files": [_source_stamp(Path(p)) for p in meta.filelist]}
        _write(self.path, row)


def _write(path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".prepared-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(row, stream, default=str)
        Path(temporary).replace(path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _refresh(meta):
    """Keep confirmed metadata edits, not one-shot upload/override permissions."""
    if meta.hdb_offer or meta.hdb_manual or meta.is_disc or meta.category not in {"MOVIE", "TV"}:
        return
    fields = {"title", "year", "category", "type", "source", "resolution", "tag", "name", "name_notag", "clean_name", "edition", "service", "imdb", "imdb_id", "tmdb", "tmdb_id", "tvdb_id", "tvmaze_id", "mal_id", "overview", "original_title", "season", "episode", "tv_pack", "audio_languages", "subtitle_languages"}
    path = release_temp_dir(meta.base_dir, meta.uuid) / "prepared_stage.json"
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(row, dict) or row.get("version") != 1 or row.get("source") != _source_stamp(Path(meta.path)) or not isinstance(row.get("meta"), dict):
            return
        losses = []
        current = _clean({key: value for key, value in meta.to_dict().items() if key in fields}, losses=losses)
        if losses:
            row['reusable'] = False
        changes = {key: current[key] for key in fields if key in current and current[key] != row["meta"].get(key)}
        if changes or losses:
            row["meta"].update(changes)
            row["saved"] = time.time()
            _write(path, row)
    except (OSError, ValueError, TypeError):
        return


async def refresh_prepared_metadata(meta, config=None):
    if getattr(meta, "no_metadata_cache", False) or default_config(config).get("stage_checkpoints_enabled", True) is False:
        return
    await asyncio.to_thread(_refresh, meta)


async def gather_with_resume(prep, meta, *, mode, config):
    # Special offer/manual pipelines intentionally keep their separate contracts.
    if meta.hdb_offer or meta.hdb_manual:
        return await prep.gather_prep(meta=meta, mode=mode)
    try:
        checkpoint = await asyncio.to_thread(PreparedStage, meta, config)
        saved = await asyncio.to_thread(checkpoint.load)
    except (OSError, ValueError, TypeError):
        checkpoint, saved = None, None
    if saved is not None:
        meta.update(saved)
        targets = meta.trackers or config.get("TRACKERS", {}).get("default_trackers") or []
        values = targets.split(',') if isinstance(targets, str) else targets
        meta.trackers = [Meta.canonical_tracker_name(str(value).strip()) for value in values if str(value).strip()]
        if meta.manual and 'MANUAL' not in meta.trackers:
            meta.trackers.insert(0, 'MANUAL')
        logger.info("[cyan]Resume: reused completed preparation for unchanged input/options. Tracker duplicate and slot checks will run again.[/cyan]")
        return meta
    result = await prep.gather_prep(meta=meta, mode=mode)
    if checkpoint is not None:
        try:
            await asyncio.to_thread(checkpoint.save, result)
        except (OSError, ValueError, TypeError):
            logger.warning("Preparation finished, but its resume checkpoint could not be saved.")
    return result

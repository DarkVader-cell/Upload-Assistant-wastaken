"""Content-addressed storage for reusable release preparation outputs."""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import stat
import threading
import time
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from src.runtime.state import atomic_write_json, default_config, file_digest, quick_path_signature, read_json, safe_digest, safe_state_snapshot

ARTIFACT_VERSION = 1
_EXCLUDED_NAMES = {"meta.json", "session_secret", "config.py"}
_EXCLUDED_SUFFIXES = {".log", ".tmp"}
_VOLATILE_META = {
    "current_version",
    "debug",
    "initial_dupes",
    "item_args",
    "release_url",
    "retry_count",
    "skip_upload_trackers",
    "tracker_status",
    "torrent_comments",
    "trumping_trackers",
    "we_are_uploading",
}


def preparation_signature(meta: Mapping[str, Any] | Any) -> str:
    getter = meta.get if hasattr(meta, "get") else lambda _key, default=None: default
    selected = {
        key: getter(key)
        for key in (
            "category",
            "comparison",
            "description_file",
            "force_upload",
            "imdb_manual",
            "manual_frames",
            "manual_type",
            "manual_year",
            "nohash",
            "screens",
            "skip_imghost_upload",
            "tmdb_manual",
            "trackers",
            "type",
        )
    }
    return safe_digest(str(sorted((key, repr(value)) for key, value in selected.items())))


def preparation_key(path: str | Path, meta: Mapping[str, Any] | Any, pipeline_signature: str = "") -> str:
    return safe_digest(f"{quick_path_signature(path)}:{preparation_signature(meta)}:{pipeline_signature}")


class ArtifactStore:
    """Deduplicate generated files while keeping release manifests immutable."""

    def __init__(self, base_dir: str | Path, config: Mapping[str, Any] | None = None) -> None:
        settings = default_config(config)
        self.enabled = bool(settings.get("preparation_artifacts_enabled", True))
        configured = Path(str(settings.get("preparation_artifacts_dir", "data/cache/preparation")))
        base = Path(base_dir).resolve()
        self.root = configured if configured.is_absolute() else base / configured
        self.objects = self.root / "objects"
        self.entries = self.root / "entries"

    def entry_path(self, key: str) -> Path:
        return self.entries / f"{safe_digest(key)}.json"

    async def contains(self, key: str) -> bool:
        return self.enabled and await asyncio.to_thread(self.entry_path(key).is_file)

    @staticmethod
    def _safe_relative(value: str) -> Path | None:
        relative = PurePosixPath(value)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            return None
        return Path(*relative.parts)

    @staticmethod
    def _meta_snapshot(meta: Mapping[str, Any]) -> dict[str, Any]:
        return safe_state_snapshot({key: value for key, value in meta.items() if key not in _VOLATILE_META})

    def _capture_sync(self, key: str, source_dir: Path, meta: Mapping[str, Any]) -> bool:
        if not self.enabled or not source_dir.is_dir():
            return False
        files: list[dict[str, Any]] = []
        for source in sorted((item for item in source_dir.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
            if source.name in _EXCLUDED_NAMES or source.suffix.lower() in _EXCLUDED_SUFFIXES or source.is_symlink():
                continue
            relative = source.relative_to(source_dir).as_posix()
            digest = file_digest(source)
            object_path = self.objects / digest[:2] / digest
            if not object_path.exists():
                object_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = object_path.with_name(f".{digest}.{os.getpid()}.{threading.get_ident()}.tmp")
                shutil.copyfile(source, temporary)
                temporary.replace(object_path)
            files.append({"path": relative, "digest": digest, "mode": stat.S_IMODE(source.stat().st_mode), "size": source.stat().st_size})
        manifest = {
            "version": ARTIFACT_VERSION,
            "created_at": time.time(),
            "meta": self._meta_snapshot(meta),
            "write_meta": (source_dir / "meta.json").is_file(),
            "files": files,
        }
        atomic_write_json(self.entry_path(key), manifest)
        return True

    async def capture(self, key: str, source_dir: str | Path, meta: Mapping[str, Any]) -> bool:
        return await asyncio.to_thread(self._capture_sync, key, Path(source_dir), meta)

    def _restore_sync(self, key: str, destination: Path) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        manifest = read_json(self.entry_path(key))
        if not isinstance(manifest, dict) or manifest.get("version") != ARTIFACT_VERSION:
            return None
        raw_files = manifest.get("files")
        if not isinstance(raw_files, list):
            return None
        destination_root = destination.expanduser().resolve()
        destination_root.mkdir(parents=True, exist_ok=True)
        validated: list[tuple[dict[str, Any], Path, Path]] = []
        for raw in raw_files:
            if not isinstance(raw, dict):
                return None
            relative = self._safe_relative(str(raw.get("path", "")))
            digest = str(raw.get("digest", ""))
            source = self.objects / digest[:2] / digest
            if relative is None or len(digest) != 64 or not source.is_file():
                return None
            target = destination_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.parent.resolve().is_relative_to(destination_root) or target.is_symlink():
                return None
            validated.append((raw, source, target))

        for raw, source, target in validated:
            temporary = target.with_name(f".{target.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            shutil.copyfile(source, temporary)
            temporary.replace(target)
            with contextlib.suppress(OSError, TypeError, ValueError):
                target.chmod(int(raw.get("mode", 0o600)))
        meta = manifest.get("meta")
        snapshot = dict(meta) if isinstance(meta, dict) else {}
        if manifest.get("write_meta"):
            atomic_write_json(destination_root / "meta.json", snapshot)
        return snapshot

    async def restore(self, key: str, destination: str | Path) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._restore_sync, key, Path(destination))

    def stats(self) -> dict[str, int]:
        entries = list(self.entries.glob("*.json")) if self.entries.exists() else []
        objects = [item for item in self.objects.glob("*/*") if item.is_file()] if self.objects.exists() else []
        return {"entries": len(entries), "objects": len(objects), "bytes": sum(item.stat().st_size for item in objects)}

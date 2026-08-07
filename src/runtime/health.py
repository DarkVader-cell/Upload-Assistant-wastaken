"""Detailed local health snapshots for operators and the Web UI dashboard."""

from __future__ import annotations

import os
import shutil
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.extensions import load_extensions
from src.runtime.artifacts import ArtifactStore
from src.runtime.checkpoints import CheckpointStore
from src.runtime.scheduler import AdaptiveScheduler


def _directory_stats(path: Path) -> dict[str, int]:
    if not path.exists():
        return {"files": 0, "bytes": 0}
    files = [item for item in path.rglob("*") if item.is_file()]
    return {"files": len(files), "bytes": sum(item.stat().st_size for item in files)}


def _tool_available(root: Path, *names: str) -> bool:
    if any(shutil.which(name) for name in names):
        return True
    binary_root = root / "bin"
    if not binary_root.exists():
        return False
    expected = {name.casefold() for name in names} | {f"{name.casefold()}.exe" for name in names}
    return any(
        candidate.name.casefold() in expected and candidate.is_file() and (os.name == "nt" or os.access(candidate, os.X_OK))
        for candidate in binary_root.rglob("*")
    )


def collect_runtime_health(base_dir: str | Path, config: Mapping[str, Any]) -> dict[str, Any]:
    root = Path(base_dir).resolve()
    default = config.get("DEFAULT", {}) if isinstance(config, Mapping) else {}
    settings = default if isinstance(default, Mapping) else {}
    artifact_store = ArtifactStore(root, config)
    checkpoints = CheckpointStore(root, config)
    scheduler = AdaptiveScheduler(root, config)
    metadata_dir = Path(str(settings.get("metadata_cache_dir", "data/cache/metadata")))
    metadata_dir = metadata_dir if metadata_dir.is_absolute() else root / metadata_dir
    tools = {
        "ffmpeg": _tool_available(root, "ffmpeg"),
        "mediainfo": _tool_available(root, "mediainfo"),
        "mkbrr": _tool_available(root, "mkbrr"),
        "bdinfo": _tool_available(root, "bdinfo"),
        "7z": _tool_available(root, "7z", "7zz", "7zr"),
        "par2": _tool_available(root, "par2", "par2create"),
        "nyuu": _tool_available(root, "nyuu"),
    }

    clients = config.get("TORRENT_CLIENTS", {}) if isinstance(config, Mapping) else {}
    client_map = clients if isinstance(clients, Mapping) else {}
    configured_clients: dict[str, dict[str, bool]] = {}
    for name, raw in client_map.items():
        if not isinstance(raw, Mapping):
            continue
        configured_clients[str(name)] = {
            "configured": bool(raw),
            "qui_proxy": bool(raw.get("qui_proxy_url")),
            "qui_native": bool(raw.get("qui_api_url") and raw.get("qui_api_key") and raw.get("qui_instance_id")),
        }

    extensions = load_extensions(root, config)
    extension_checks: dict[str, Any] = {}
    for name, check in extensions.health_checks.items():
        try:
            extension_checks[name] = dict(check())
        except Exception as error:
            extension_checks[name] = {"healthy": False, "error": str(error)}

    return {
        "status": "healthy" if tools["ffmpeg"] and tools["mediainfo"] else "degraded",
        "generated_at": time.time(),
        "cache": {"metadata": _directory_stats(metadata_dir), "artifacts": artifact_store.stats()},
        "checkpoints": checkpoints.stats(),
        "scheduler": scheduler.snapshot(),
        "clients": configured_clients,
        "tools": tools,
        "extensions": {**extensions.snapshot(), "health": extension_checks},
    }

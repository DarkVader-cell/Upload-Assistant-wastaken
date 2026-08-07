"""Small, dependency-free helpers for durable runtime state."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SENSITIVE_KEY_PARTS = ("api_key", "cookie", "credential", "passkey", "password", "secret", "session", "token")


def default_config(config: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(config, Mapping):
        return {}
    value = config.get("DEFAULT", config)
    return value if isinstance(value, Mapping) else {}


def atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None


def safe_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def safe_state_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    """Copy runtime state while omitting fields likely to contain credentials."""
    return {
        key: item
        for key, item in value.items()
        if not any(part in key.casefold() for part in SENSITIVE_KEY_PARTS)
    }


def quick_path_signature(path: str | Path) -> str:
    """Return a fast source signature suitable for planning and checkpoints.

    It includes every relative path, size and nanosecond mtime. Immutable
    artifact blobs are still addressed by their complete byte hash.
    """
    source = Path(path).expanduser().resolve()
    digest = hashlib.sha256()
    digest.update(str(source).encode("utf-8", errors="surrogateescape"))
    candidates = [source] if source.is_file() else sorted((item for item in source.rglob("*") if item.is_file()), key=lambda item: item.as_posix())
    for item in candidates:
        try:
            stat = item.stat()
            relative = item.name if source.is_file() else item.relative_to(source).as_posix()
            digest.update(relative.encode("utf-8", errors="surrogateescape"))
            digest.update(f"\0{stat.st_size}\0{stat.st_mtime_ns}\0".encode())
        except OSError:
            continue
    return digest.hexdigest()


def file_digest(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()

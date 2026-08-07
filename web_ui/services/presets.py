"""Persistence helpers for shared Web UI argument presets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_argument_presets(path: Path, limit: int) -> list[dict[str, str]]:
    try:
        if not path.exists():
            return []
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except OSError, TypeError, ValueError:
        return []
    if not isinstance(raw, list):
        return []
    presets: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        arguments = item.get("arguments")
        if isinstance(name, str) and isinstance(arguments, str) and name.strip() and arguments.strip():
            presets.append({"name": name.strip(), "arguments": arguments.strip()})
    return presets[-limit:]


def save_argument_presets(path: Path, presets: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".json.tmp")
    temporary_path.write_text(json.dumps(presets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(path)

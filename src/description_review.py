"""Persistent, execution-scoped description drafts for CLI and WebUI review."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_REVIEW_FILE = "description_review.json"


def is_meaningful_description(value: object) -> bool:
    """Return whether a value contains actual description text."""
    if not isinstance(value, str):
        return False
    normalized = value.strip().casefold()
    return bool(normalized) and normalized not in {"0", "none", "null", "undefined"}


def review_path(temp_dir: Path) -> Path:
    return temp_dir / _REVIEW_FILE


def load_review(temp_dir: Path) -> dict[str, Any]:
    try:
        value = json.loads(review_path(temp_dir).read_text(encoding="utf-8"))
    except OSError, ValueError, TypeError:
        return {}
    return value if isinstance(value, dict) else {}


def save_review(temp_dir: Path, content: str, version: int, source_path: str | None = None) -> dict[str, Any]:
    """Atomically persist a user draft without relying on a browser path."""
    temp_dir.mkdir(parents=True, exist_ok=True)
    payload = {"content": content, "version": version}
    if source_path:
        payload["source_path"] = str(Path(source_path).expanduser().resolve(strict=False))
    path = review_path(temp_dir)
    temporary = path.with_suffix(f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return payload


def save_tracker_description(temp_dir: Path, tracker: str, content: str) -> Path:
    """Atomically retain the exact tracker-specific description payload."""
    temp_dir.mkdir(parents=True, exist_ok=True)
    path = temp_dir / f"[{tracker}]DESCRIPTION.txt"
    temporary = path.with_suffix(f".tmp.{os.getpid()}")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
    return path


def source_items(meta: dict[str, Any]) -> list[dict[str, str]]:
    """Return inspectable read-only inputs used to build the base description."""
    items: list[dict[str, str]] = []
    for key, label in (
        ("description", "Tracker description"),
        ("description_link_content", "Description link"),
        ("description_file_content", "Description file"),
        ("description_template_content", "Template"),
        ("description_nfo_content", "NFO"),
    ):
        content = meta.get(key)
        if is_meaningful_description(content):
            items.append({"key": key, "label": label, "content": content})
    return items


def _review_matches_source(meta: dict[str, Any], review: dict[str, Any]) -> bool:
    """Reject a draft saved for a different release sharing the same basename."""
    current_path = meta.get("path")
    saved_path = review.get("source_path")
    if not isinstance(current_path, str) or not current_path:
        return True
    if not isinstance(saved_path, str) or not saved_path:
        return False
    return Path(current_path).expanduser().resolve(strict=False) == Path(saved_path).expanduser().resolve(strict=False)


def draft(meta: dict[str, Any], temp_dir: Path) -> tuple[str, int]:
    review = load_review(temp_dir)
    if not _review_matches_source(meta, review):
        review = {}
    content = review.get("content")
    if is_meaningful_description(content):
        try:
            version = int(review.get("version", 0) or 0)
        except TypeError, ValueError:
            version = 0
        return content, version
    override = meta.get("description_override")
    if is_meaningful_description(override):
        return override, 0
    items = source_items(meta)
    return (items[0]["content"] if items else ""), 0


def apply_saved_draft(meta: Any) -> None:
    """Synchronize a saved WebUI draft into the live Meta object at use time."""
    temp_dir = Path(meta.base_dir) / "tmp" / meta.uuid
    review = load_review(temp_dir)
    if not _review_matches_source(meta.to_dict(), review):
        return
    content = review.get("content")
    if is_meaningful_description(content):
        meta.description_override = content
        # Several tracker adapters use ``meta.description`` directly. Keep both
        # views synchronized so a WebUI edit
        # is honored by every tracker-specific description builder.
        meta.description = content
        meta.saved_description = bool(content)


def get_base_description(meta: Any) -> str:
    """Return the one authoritative base description for an upload."""
    apply_saved_draft(meta)
    description = getattr(meta, "description", "") or ""
    return description if is_meaningful_description(description) else ""

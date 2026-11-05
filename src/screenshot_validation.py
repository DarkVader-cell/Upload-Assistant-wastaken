"""Validation for screenshots rendered into upload descriptions."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from src.meta import Meta
from src.tracker_images import get_tracker_image_collection

_IMAGE_TAG_RE = re.compile(r"\[img(?:=[^\]]+)?\]\s*(?P<url>https?://[^\s\[]+)\s*\[/img\]", re.IGNORECASE)
_HTML_IMAGE_RE = re.compile(r"<img\b[^>]*?\bsrc=[\"'](?P<url>https?://[^\"']+)", re.IGNORECASE)


def _is_lossless_image(image: dict[str, Any]) -> bool:
    """Reject screenshots that are explicitly JPEG; preserve opaque CDN URLs."""
    candidates = [image.get("local_file_path"), image.get("raw_url")]
    for candidate in candidates:
        value = str(candidate or "").strip()
        if not value:
            continue
        suffix = Path(urlsplit(value).path).suffix.casefold()
        if suffix in {".jpg", ".jpeg"}:
            return False
    return True


def description_screenshot_count(description: str, meta: Meta, tracker: str) -> int:
    """Count unique lossless hosted screenshots whose full URLs occur in description."""
    if not isinstance(description, str):
        return 0
    rendered_urls = {match.group("url").strip() for match in (*_IMAGE_TAG_RE.finditer(description), *_HTML_IMAGE_RE.finditer(description))}
    if not rendered_urls:
        return 0

    images = get_tracker_image_collection(meta, tracker, "screenshots")
    eligible = {
        str(image.get("raw_url")).strip()
        for image in images
        if isinstance(image, dict) and image.get("raw_url") and _is_lossless_image(image)
    }
    return len(rendered_urls & eligible)


def validate_description_screenshots(description: str, meta: Meta, tracker: str, minimum: int = 3) -> None:
    """Require video descriptions to contain the requested full, lossless screenshots."""
    if str(meta.category or "").upper() not in {"MOVIE", "TV"}:
        return
    count = description_screenshot_count(description, meta, tracker)
    if count < minimum:
        raise ValueError(f"{tracker}: description must include at least {minimum} lossless screenshots (found {count})")

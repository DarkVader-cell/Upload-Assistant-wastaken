"""Release-name safety checks shared by the CLI, trackers, and Web UI."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_YEAR_RE = re.compile(r"\b(?:18|19|20)\d{2}\b")
_RESOLUTION_RE = re.compile(r"^(?:2160|1440|1080|720|576|540|480|432|360|288)p$", re.IGNORECASE)


def _text(value: Any) -> str:
    return str(value or "").strip()


def is_release_year(value: Any) -> bool:
    """Whether *value* is a usable release year rather than a null placeholder."""
    value = _text(value)
    return bool(re.fullmatch(r"(?:18|19|20)\d{2}", value))


def is_release_resolution(value: Any) -> bool:
    """Whether *value* is a standard vertical video resolution."""
    return bool(_RESOLUTION_RE.fullmatch(_text(value)))


def release_metadata_issues(meta: Mapping[str, Any]) -> dict[str, str]:
    """Return mandatory shared release fields that need user correction.

    Movie years are part of the normal tracker title contract unless the user
    explicitly requested ``--no-year``.  Resolution is required for ordinary
    video files, while DVD discs intentionally use DVD sizing instead.
    """
    issues: dict[str, str] = {}
    category = _text(meta.get("category")).upper()
    media_type = _text(meta.get("type")).upper()
    is_dvd = _text(meta.get("is_disc")).upper() == "DVD" or _text(meta.get("source")).upper() == "DVD"

    if category == "MOVIE" and not bool(meta.get("no_year")):
        year = meta.get("manual_year") or meta.get("year") or meta.get("search_year")
        if not is_release_year(year):
            issues["year"] = "A four-digit release year is required for movie uploads."

    if category in {"MOVIE", "TV"} and not is_dvd and media_type not in {"", "DISC", "DVD"} and not is_release_resolution(meta.get("resolution")):
        issues["resolution"] = "A video resolution such as 1080p is required."
    return issues


def tracker_release_name_issues(meta: Mapping[str, Any], submitted_name: Any) -> dict[str, str]:
    """Validate the exact tracker title immediately before its HTTP request.

    Trackers may alter a title after the shared release name has been built.
    This guard catches accidental removal/stringification of mandatory fields
    (for example an IMDb ``None`` replacing a valid movie year).
    """
    issues = release_metadata_issues(meta)
    name = _text(submitted_name)
    category = _text(meta.get("category")).upper()

    if name and category == "MOVIE" and not bool(meta.get("no_year")) and not _YEAR_RE.search(name):
        issues["year"] = "The tracker-specific title has no valid four-digit release year."

    resolution = _text(meta.get("resolution"))
    if name and is_release_resolution(resolution) and re.search(rf"(?<![A-Za-z0-9]){re.escape(resolution)}(?![A-Za-z0-9])", name, re.IGNORECASE) is None:
        issues["resolution"] = f"The tracker-specific title is missing {resolution}."
    return issues

from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
from collections.abc import Mapping, MutableMapping
from typing import Any

from src.console import console

DETACHED_METADATA_REQUEST_PREFIX = "__UA_METADATA_REQUEST__:"
DETACHED_RELEASE_METADATA_REQUEST_PREFIX = "__UA_RELEASE_METADATA_REQUEST__:"


def normalize_imdb_id(value: Any) -> int:
    text = str(value or "").strip().lower()
    if not text:
        return 0
    if text.startswith("http"):
        match = re.search(r"/title/(tt\d+)", urllib.parse.urlparse(text).path, flags=re.IGNORECASE)
        text = match.group(1).lower() if match else ""
    if text.startswith("tt"):
        text = text[2:]
    if not text.isdigit() or int(text) <= 0:
        raise ValueError("IMDb ID must look like tt1234567")
    return int(text)


def normalize_tmdb_id(value: Any, category: Any = None) -> tuple[int, str]:
    text = str(value or "").strip().lower()
    normalized_category = str(category or "").strip().upper()
    if not text:
        return 0, normalized_category

    if text.startswith("http"):
        parts = [part for part in urllib.parse.urlparse(text).path.split("/") if part]
        for index, part in enumerate(parts[:-1]):
            if part in {"movie", "tv"} and parts[index + 1].isdigit():
                text = f"{part}/{parts[index + 1]}"
                break

    if "/" in text:
        type_part, id_part = text.split("/", 1)
        if type_part not in {"movie", "tv"}:
            raise ValueError("TMDb ID must use movie/12345 or tv/12345")
        normalized_category = "MOVIE" if type_part == "movie" else "TV"
        text = id_part

    if normalized_category not in {"MOVIE", "TV"}:
        raise ValueError("TMDb ID needs a movie/ or tv/ prefix")
    if not text.isdigit() or int(text) <= 0:
        raise ValueError("TMDb ID must look like movie/12345 or tv/12345")
    return int(text), normalized_category


def metadata_request(meta: Mapping[str, Any]) -> dict[str, Any]:
    imdb_optional = bool(meta.get("imdb_optional", False))
    return {
        "title": str(meta.get("title") or meta.get("filename") or meta.get("uuid") or ""),
        "year": meta.get("year") or meta.get("search_year") or meta.get("manual_year") or "",
        "category": str(meta.get("category") or "").upper(),
        "tmdb_id": int(meta.get("tmdb_id") or 0),
        "imdb_id": int(meta.get("imdb_id") or 0),
        "missing": [name for name in ("tmdb_id", "imdb_id") if int(meta.get(name) or 0) == 0 and not (name == "imdb_id" and imdb_optional)],
    }


def encode_metadata_request(meta: Mapping[str, Any]) -> str:
    return f"{DETACHED_METADATA_REQUEST_PREFIX}{json.dumps(metadata_request(meta), separators=(',', ':'))}"


def parse_detached_metadata_request(line: str) -> dict[str, Any] | None:
    if not line.startswith(DETACHED_METADATA_REQUEST_PREFIX):
        return None
    try:
        payload = json.loads(line[len(DETACHED_METADATA_REQUEST_PREFIX) :])
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def release_metadata_request(meta: Mapping[str, Any], issues: Mapping[str, str]) -> dict[str, Any]:
    """Create the Web UI payload for missing release-name fields."""
    fields = [field for field in ("year", "resolution") if field in issues]
    return {
        "title": str(meta.get("title") or meta.get("filename") or meta.get("uuid") or ""),
        "category": str(meta.get("category") or "").upper(),
        "name": str(meta.get("name") or ""),
        "fields": fields,
        "values": {field: meta.get(field) or "" for field in fields},
        "issues": {field: str(issues[field]) for field in fields},
    }


def encode_release_metadata_request(meta: Mapping[str, Any], issues: Mapping[str, str]) -> str:
    return f"{DETACHED_RELEASE_METADATA_REQUEST_PREFIX}{json.dumps(release_metadata_request(meta, issues), separators=(',', ':'))}"


def parse_detached_release_metadata_request(line: str) -> dict[str, Any] | None:
    if not line.startswith(DETACHED_RELEASE_METADATA_REQUEST_PREFIX):
        return None
    try:
        payload = json.loads(line[len(DETACHED_RELEASE_METADATA_REQUEST_PREFIX) :])
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def parse_release_metadata_submission(payload: Any, requested_fields: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError("Release metadata response must be an object")
    fields = {str(field) for field in requested_fields if isinstance(field, str)}
    result: dict[str, Any] = {}
    if "year" in fields:
        year = str(payload.get("year") or "").strip()
        if not re.fullmatch(r"(?:18|19|20)\d{2}", year):
            raise ValueError("Year must be a four-digit value between 1800 and 2099")
        result["year"] = int(year)
    if "resolution" in fields:
        resolution = str(payload.get("resolution") or "").strip().lower()
        if not re.fullmatch(r"(?:2160|1440|1080|720|576|540|480|432|360|288)p", resolution):
            raise ValueError("Resolution must be a value such as 1080p")
        result["resolution"] = resolution
    if not result:
        raise ValueError("No release metadata fields were requested")
    return result


def apply_release_metadata_submission(meta: MutableMapping[str, Any], payload: Any, requested_fields: Any) -> set[str]:
    parsed = parse_release_metadata_submission(payload, requested_fields)
    changed: set[str] = set()
    for key, value in parsed.items():
        if meta.get(key) != value:
            meta[key] = value
            changed.add(key)
        if key == "year":
            meta["manual_year"] = value
            meta["search_year"] = str(value)
    return changed


def request_release_metadata(meta: MutableMapping[str, Any], issues: Mapping[str, str]) -> set[str]:
    """Ask for release fields, using a machine-readable checkpoint when detached."""
    detached_job_id = os.environ.get("UA_DETACHED_JOB_ID", "").strip()
    request_data = release_metadata_request(meta, issues)
    if detached_job_id:
        print(encode_release_metadata_request(meta, issues), flush=True)
        response_line = sys.stdin.readline()
        if not response_line:
            raise RuntimeError("Detached release-metadata prompt closed before values were supplied")
        try:
            payload = json.loads(response_line)
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid release-metadata response received from Web UI") from exc
        return apply_release_metadata_submission(meta, payload, request_data["fields"])

    import cli_ui

    response: dict[str, str] = {}
    if "year" in request_data["fields"]:
        response["year"] = cli_ui.ask_string("Release year (YYYY): ")
    if "resolution" in request_data["fields"]:
        response["resolution"] = cli_ui.ask_string("Video resolution (for example 1080p): ")
    return apply_release_metadata_submission(meta, response, request_data["fields"])


def should_request_metadata(meta: Mapping[str, Any], detached: bool = False) -> bool:
    if meta.get("no_prompt_missing_ids", False):
        return False
    tmdb_missing = int(meta.get("tmdb_id") or 0) == 0
    imdb_missing = int(meta.get("imdb_id") or 0) == 0 and not meta.get("imdb_optional", False)
    missing_id = tmdb_missing or imdb_missing
    if detached and missing_id:
        return True
    return bool(meta.get("prompt_missing_ids", False)) and (missing_id or (detached and bool(meta.get("quickie_search", False))))


def parse_metadata_submission(payload: Any, current_category: Any = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Metadata response must be an object")
    tmdb_id, category = normalize_tmdb_id(payload.get("tmdb_id"), payload.get("category") or current_category)
    imdb_id = normalize_imdb_id(payload.get("imdb_id"))
    if tmdb_id == 0 and imdb_id == 0:
        raise ValueError("Enter at least one TMDb or IMDb ID")
    return {"tmdb_id": tmdb_id, "imdb_id": imdb_id, "category": category}


def apply_metadata_submission(meta: MutableMapping[str, Any], payload: Any) -> set[str]:
    parsed = parse_metadata_submission(payload, meta.get("category"))
    changed: set[str] = set()
    for key in ("tmdb_id", "imdb_id"):
        value = parsed[key]
        if key in payload and value != int(meta.get(key) or 0):
            meta[key] = value
            changed.add(key)
    if parsed["tmdb_id"] and parsed["category"] != str(meta.get("category") or "").upper():
        meta["category"] = parsed["category"]
        changed.add("category")
    return changed


def request_missing_metadata(meta: MutableMapping[str, Any]) -> set[str]:
    request_data = metadata_request(meta)
    detached_job_id = os.environ.get("UA_DETACHED_JOB_ID", "").strip()
    if detached_job_id:
        print(encode_metadata_request(meta), flush=True)
        response_line = sys.stdin.readline()
        if not response_line:
            raise RuntimeError("Detached metadata prompt closed before IDs were supplied")
        try:
            payload = json.loads(response_line)
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid metadata response received from Web UI") from exc
        return apply_metadata_submission(meta, payload)

    import cli_ui

    console.print("[bold yellow]Automatic metadata lookup did not resolve the requested IDs.[/bold yellow]")
    tmdb_value = cli_ui.ask_string(f"TMDb ID (movie/12345 or tv/12345; Enter keeps {request_data['tmdb_id'] or 'missing'}): ")
    imdb_value = ""
    if not meta.get("imdb_optional", False):
        imdb_value = cli_ui.ask_string(f"IMDb ID (tt1234567; Enter keeps {request_data['imdb_id'] or 'missing'}): ")
    payload = {
        "tmdb_id": tmdb_value or request_data["tmdb_id"],
        "imdb_id": imdb_value or request_data["imdb_id"],
        "category": request_data["category"],
    }
    return apply_metadata_submission(meta, payload)

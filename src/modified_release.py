from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

MODIFIED_RELEASE_REASON = "source appears renamed or modified from its original release name; verify the file hash and source provenance"
ARR_RELEASE_ID_TOKENS = ("{tmdb-", "{imdb-", "{tvdb-")
MEDIA_EXTENSIONS = {".mkv", ".mp4", ".avi", ".ts", ".m2ts", ".m4v", ".mov", ".wmv", ".mpg", ".mpeg", ".vob", ".iso"}


def candidate_release_names(paths: Iterable[str]) -> list[str]:
    names: list[str] = []
    for path in paths:
        base = Path(str(path).strip()).name
        if not base:
            continue
        base_path = Path(base)
        if base_path.suffix.lower() in MEDIA_EXTENSIONS:
            base = base_path.stem
        if base not in names:
            names.append(base)
    return names


def detect_modified_release(paths: Iterable[str], group: str = "", *, is_disc: bool = False, personal_release: bool = False) -> str | None:
    if is_disc or personal_release:
        return None
    names = candidate_release_names(paths)
    if any(any(token in name.lower() for token in ARR_RELEASE_ID_TOKENS) for name in names):
        return MODIFIED_RELEASE_REASON
    normalized_group = group.strip().lstrip("-")
    if not normalized_group:
        return None
    suffix = f"-{normalized_group}".upper()
    for name in names:
        if any(char.isspace() for char in name) and not any(marker in name for marker in "()[]{}") and name.upper().endswith(suffix):
            return MODIFIED_RELEASE_REASON
    return None


def archived_media_renamed(archived_files: Iterable[Mapping[str, object]], local_media_filename: str) -> tuple[bool, bool]:
    local_name = local_media_filename.strip()
    found_media = False
    for archived_file in archived_files:
        archived_name = str(archived_file.get("name") or "").strip().replace("\\", "/").rsplit("/", 1)[-1]
        if Path(archived_name).suffix.lower() not in MEDIA_EXTENSIONS:
            continue
        found_media = True
        if archived_name == local_name:
            return False, True
    return found_media, found_media

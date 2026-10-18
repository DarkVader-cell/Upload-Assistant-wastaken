"""Manual HDBits offers with HDB images and encrypted PrivateBin sharing only."""

from __future__ import annotations

import contextlib
import os
import re
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from src.get_name import NameManager
from src.meta import Meta
from src.privatebin import DEFAULT_ENDPOINT, PrivateBinError, create_paste
from src.region import get_service
from src.screenshot_manifest import files as manifest_files
from src.trackers.hdbits import HDBits

CATEGORY_NAMES = {1: "Movie", 2: "TV", 3: "Documentary", 4: "Music"}
CODEC_NAMES = {1: "H.264", 2: "MPEG-2", 3: "VC-1", 4: "XviD", 5: "H.265", 6: "VP9"}
MEDIUM_NAMES = {1: "Blu-ray / HD DVD", 3: "Encode", 4: "Capture", 5: "Remux", 6: "WEB-DL"}


def validate_offer_options(meta: Meta) -> None:
    """Reject incompatible actions rather than letting upload options leak through."""
    if any((meta.usenet, meta.site_upload, meta.site_upload_queue, meta.site_check, meta.prepare_only, meta.dry_run_plan, meta.cleanup, meta.comparison, meta.skip_imghost_upload)):
        raise ValueError("--hdb-offer cannot be combined with Usenet, site actions, prepare-only, plan, cleanup, comparisons or disabled image uploads")
    if meta.screens <= 0:
        raise ValueError("--hdb-offer requires screenshots (--screens greater than zero)")


def _id(value: object, label: str, prefix: str = "") -> str:
    if value in (None, "", 0, "0"):
        return ""
    text = str(value)
    if prefix and text.startswith(prefix):
        text = text[len(prefix):]
    if not re.fullmatch(r"[0-9]{1,10}", text) or int(text) <= 0:
        raise ValueError(f"Invalid {label} ID")
    return str(int(text))


def _plain(value: object) -> str:
    # Metadata/report text must not close a hide block or inject BBCode.
    text = str(value or "").replace("[", "\uff3b").replace("]", "\uff3d")
    return "".join(char for char in text if char in "\n\t" or (ord(char) >= 32 and not 127 <= ord(char) <= 159)).strip()


def validate_image_bbcode(value: str | None) -> str:
    """Accept only complete HDB image/gallery BBCode, never an HTML error page."""
    if not value:
        raise ValueError("HDB image upload failed or returned no BBCode")
    pattern = r"(?:\[url=(https://[^\s\[\]]+)\])?\[img\](https://[^\s\[\]]+)\[/img\](?(1)\[/url\])"
    matches = list(re.finditer(pattern, value, flags=re.IGNORECASE))
    remainder = re.sub(pattern, "", value, flags=re.IGNORECASE)
    if not matches or remainder.strip():
        raise ValueError("HDB image upload returned unexpected BBCode")
    for match in matches:
        for url in match.groups():
            if url is None:
                continue
            if any(ord(char) < 33 or ord(char) > 126 or char in "\"'<>\\" for char in url):
                raise ValueError("HDB image upload returned an unsafe URL")
            parts = urlsplit(url)
            # BBCODE.clean_hdb_description already recognizes HDB's t.hdbits.org thumbnails.
            # Keep exact hosts: no wildcard subdomains, userinfo or explicit ports.
            if parts.scheme != "https" or parts.netloc not in ("img.hdbits.org", "t.hdbits.org") or not parts.path.startswith("/") or parts.path == "/":
                raise ValueError("HDB image upload returned a non-HDB image/gallery URL")
    thumbnails = [match.group() for match in matches]
    return "\n".join(" ".join(thumbnails[index:index + 2]) for index in range(0, len(thumbnails), 2))


def _tv_number(value: object, prefix: str, label: str) -> str:
    text = str(value if value is not None else "")
    if text.upper().startswith(prefix):
        text = text[1:]
    if not re.fullmatch(r"[0-9]{1,4}", text):
        raise ValueError(f"HDB offer requires a single numeric {label}; ranges must be handled manually")
    return str(int(text))


async def offer_fields(meta: Meta, tracker: HDBits) -> dict[str, str]:
    if meta.category not in ("MOVIE", "TV"):
        raise ValueError("HDBits offers support only MOVIE and TV")
    category = await tracker.get_type_category_id(meta)
    codec = await tracker.get_type_codec_id(meta)
    medium = await tracker.get_type_medium_id(meta)
    if category not in CATEGORY_NAMES or codec not in CODEC_NAMES or medium not in MEDIUM_NAMES:
        raise ValueError("Unsupported HDB offer category, codec or medium; refusing to guess")
    imdb = _id(meta.imdb_id, "IMDb", "tt")
    tmdb = _id(meta.tmdb_id, "TMDB")
    tvdb = _id(meta.tvdb_id, "TVDB")
    if not (imdb or tmdb):
        raise ValueError("HDB offer requires an IMDb or TMDB ID; supply --imdb or --tmdb")
    if any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in meta.name):
        raise ValueError("HDB offer title contains control characters")
    title = await tracker.get_name(meta)
    if not title.strip() or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in title) or "[" in title or "]" in title:
        raise ValueError("HDB offer title is empty or contains control/markup characters")
    options = tracker.config.get("TRACKERS", {}).get("HDBITS", {})
    internal = bool(meta.tag and options.get("internal") is True and meta.tag.removeprefix("-") in options.get("internal_groups", []))
    return {
        "Title": title,
        "IMDb link": f"https://www.imdb.com/title/tt{imdb.zfill(7)}/" if imdb else "Not available",
        "TMDB link": f"https://www.themoviedb.org/{'tv' if meta.category == 'TV' else 'movie'}/{tmdb}" if tmdb else "Not available",
        "TMDB ID": tmdb or "Not available",
        "TVDB ID": tvdb or "Not available",
        "Season": _tv_number(meta.season, "S", "season") if meta.category == "TV" else "Not applicable",
        "Episode": ("Season pack (leave blank)" if meta.tv_pack else _tv_number(meta.episode, "E", "episode")) if meta.category == "TV" else "Not applicable",
        "Category": f"{CATEGORY_NAMES[category]} ({category})",
        "Codec": f"{CODEC_NAMES[codec]} ({codec})",
        "Medium": f"{MEDIUM_NAMES[medium]} ({medium})",
        "Origin": "Internal (1)" if internal else "External (0)",
        "Exclusive": "Yes" if meta.exclusive else "No",
    }


def _report(meta: Meta) -> tuple[str, str]:
    if meta.is_disc == "BDMV":
        reports = [str(disc.get("summary") or "").strip() for disc in meta.discs if disc.get("type") == "BDMV"]
        report = "\n\n".join(report for report in reports if report)
        label = "BDInfo"
    else:
        path = Path(meta.base_dir) / "tmp" / meta.uuid / "MEDIAINFO_CLEANPATH.txt"
        report = path.read_text(encoding="utf-8").strip()
        label = "MediaInfo"
    if not report:
        raise ValueError("HDB offer requires a nonempty MediaInfo/BDInfo report")
    return label, _plain(report)


async def _source_attribution(meta: Meta) -> str:
    if meta.type != "WEBDL":
        return ""
    services = cast(dict[str, str], await get_service(get_services_only=True))
    code = services.get(meta.service, "")
    if not code:
        return ""
    longname = meta.service_longname
    if not longname:
        # Same catalogue fallback as metadata preparation, including MA aliases.
        longname = max((name for name, value in services.items() if value == code), key=len)
    return f"This release was sourced from {_plain(longname)}"


def _write_offer_link(path: Path, link: str) -> None:
    # Exclusive creation avoids following links and keeps the fragment private
    # from the first byte, even with a permissive umask.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(link + "\n")


async def generate_hdb_offer(meta: Meta, config: dict[str, Any]) -> dict[str, Path]:
    """Validate, upload HDB screenshots, save drafts, then share encrypted text."""
    validate_offer_options(meta)
    tracker = HDBits(config)
    if not tracker.username or not tracker.passkey:
        raise ValueError("HDBITS username and passkey are required for img.hdbits.org")
    # Naming must not prompt/query catalogs for unrelated configured trackers.
    meta.trackers = ["HDBITS"]
    meta.name_notag, meta.name, meta.clean_name, meta.potential_missing = await NameManager(config).get_name(meta)
    fields = await offer_fields(meta, tracker)
    label, report = _report(meta)
    if not manifest_files(meta.base_dir, meta.uuid, "main"):
        raise ValueError("HDBits offer requires validated registered screenshots")
    images = validate_image_bbcode(await tracker.hdbimg_upload(meta))

    # No synopsis, cached tracker descriptions, image lists, artwork or reviews.
    source = await _source_attribution(meta)
    directory = Path(meta.base_dir) / "tmp" / meta.uuid
    sections = ([source] if source else []) + [f"[hide={label}]\n{report}\n[/hide]", f"[center]{images}[/center]"]
    description = "\n\n".join(sections) + "\n"
    form = "\n".join(f"{key}: {value}" for key, value in fields.items()) + "\n"
    contents = {"HDB_OFFER_TITLE.txt": str(fields["Title"]) + "\n", "HDB_OFFER_DESCRIPTION.txt": description, "HDB_OFFER_FORM.txt": form}
    paths: dict[str, Path] = {}
    for filename, content in contents.items():
        path = directory / filename
        path.write_text(content, encoding="utf-8")
        paths[filename] = path
    # BBCode must bypass Rich markup parsing, including in WebUI subprocess logs.
    print("\nHDBits offer form (manual submission only)\n" + form)
    print("Description (BBCode):\n" + description)
    print("Saved offer drafts:\n" + "\n".join(str(path) for path in paths.values()))
    link_path = directory / "HDB_OFFER_LINK.txt"
    try:
        # A failed rerun must not advertise a stale share link as its result.
        link_path.unlink(missing_ok=True)
        paste_text = f"Title:\n{fields['Title']}\n\nFORM:\n{form}\nDescription (BBCode):\n{description}"
        endpoint = config.get("TRACKERS", {}).get("HDBITS", {}).get("offer_paste_url", DEFAULT_ENDPOINT)
        link = await create_paste(paste_text, endpoint)
        _write_offer_link(link_path, link)
    except (PrivateBinError, OSError):
        # Do not echo endpoints, responses or exceptions: they can carry secrets.
        with contextlib.suppress(OSError):
            link_path.unlink(missing_ok=True)
        print("Warning: encrypted offer sharing unavailable; use the local HDB_OFFER_TITLE/DESCRIPTION/FORM.txt drafts listed above. No new share link was saved.")
    else:
        paths[link_path.name] = link_path
        print("Encrypted offer link (anyone with this full link can read it; expires in one week):\n" + link)
    return paths

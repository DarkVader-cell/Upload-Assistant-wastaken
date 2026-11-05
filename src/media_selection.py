"""Explicit Matroska metadata selections. Preserved fields are not PII-certified."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

FONT_MIMES = frozenset(
    {
        "application/x-truetype-font",
        "application/x-font-ttf",
        "application/x-font-opentype",
        "application/vnd.ms-opentype",
        "font/ttf",
        "font/otf",
        "font/collection",
        "application/font-sfnt",
    }
)


def cleanup_options(value=None):
    value = {} if value is None else value
    allowed = {
        "remove_tag_names",
        "remove_track_names",
        "remove_attachment_ids",
        "clear_title",
        "clear_chapter_names",
        "remove_dates",
        "container_title",
        "track_overrides",
        "tag_edits",
    }
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError("Invalid metadata selection")
    result = {}
    for key in ["clear_title", "clear_chapter_names", "remove_dates"]:
        flag = value.get(key, key == "remove_dates")
        if type(flag) is not bool:
            raise ValueError("Metadata choices must be checkboxes")
        result[key] = flag
    for key in ["remove_tag_names", "remove_track_names", "remove_attachment_ids"]:
        entries = value.get(key, [])
        if not isinstance(entries, list) or len(entries) > 256 or any(not isinstance(entry, str) for entry in entries):
            raise ValueError("Invalid metadata field selection")
        if key == "remove_tag_names":
            if any(not re.fullmatch(r"[A-Za-z0-9_. -]{1,100}", entry) for entry in entries):
                raise ValueError("Unsupported metadata tag name")
            result[key] = sorted({entry.upper() for entry in entries})
        else:
            if any(not re.fullmatch(r"[0-9]{1,8}", entry) for entry in entries):
                raise ValueError("Invalid track/attachment selection")
            result[key] = sorted(set(entries))
    title = value.get("container_title")
    if title is not None and (not isinstance(title, str) or len(title) > 500 or any(ord(c) < 32 for c in title) or "cardinaldl" in title.casefold()):
        raise ValueError("Invalid container title")
    if title is not None and result["clear_title"]:
        raise ValueError("Choose either a container title or its removal")
    result["container_title"] = title
    overrides = value.get("track_overrides", {})
    if not isinstance(overrides, dict) or len(overrides) > 128:
        raise ValueError("Invalid track edits")
    for key, fields in overrides.items():
        if (
            not isinstance(key, str)
            or not re.fullmatch(r"[0-9]{1,8}", key)
            or not isinstance(fields, dict)
            or set(fields) - {"name", "language", "default", "forced", "hearing_impaired", "commentary"}
        ):
            raise ValueError("Unsupported track edit")
        for field, text in fields.items():
            if field in {"default", "forced", "hearing_impaired", "commentary"}:
                if type(text) is not bool:
                    raise ValueError("Track flags must be checkboxes")
            elif not isinstance(text, str) or len(text) > 500 or any(ord(c) < 32 for c in text) or "cardinaldl" in text.casefold():
                raise ValueError("Invalid track label/language")
        if "language" in fields and not re.fullmatch(r"[a-zA-Z]{2,3}(?:-[A-Za-z0-9]{2,8})*", fields["language"]):
            raise ValueError("Use a valid language code")
        if key in result["remove_track_names"] and "name" in fields:
            raise ValueError("Choose either a track name or its removal")
    result["track_overrides"] = overrides
    from src.media_template import validate_options

    result["tag_edits"] = validate_options(tags=value.get("tag_edits", {}))["tags"]
    return result


def readable_tags(xml):
    xml = re.sub(r"""<!DOCTYPE\s+Tags\s+SYSTEM\s+["']matroskatags\.dtd["']\s*>""", "", xml, flags=re.I)
    if len(xml) > 4 * 1024 * 1024 or "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
        raise ValueError("Unsupported MKV tags document")
    root = ET.fromstring(xml) if xml.strip() else ET.Element("Tags")
    if root.tag != "Tags":
        raise ValueError("Invalid MKV tags document")
    rows = []
    editable_nodes = {
        id(node)
        for tag in root.findall("Tag")
        if not any(child.tag in {"TrackUID", "ChapterUID", "AttachmentUID", "EditionUID"} for child in (tag.find("Targets") if tag.find("Targets") is not None else []))
        for node in tag.findall("Simple")
    }
    reserved = {
        "IMDB",
        "TMDB",
        "IMDB_ID",
        "TMDB_ID",
        "ENCODER",
        "ENCODER_SETTINGS",
        "WRITING_APPLICATION",
        "MUXING_APPLICATION",
        "DURATION",
        "BPS",
        "NUMBER_OF_FRAMES",
        "NUMBER_OF_BYTES",
        "FRAME_RATE",
        "WIDTH",
        "HEIGHT",
        "CODEC",
        "CODEC_ID",
    }
    for node in root.iter("Simple"):
        name = node.findtext("Name", "")
        value = node.findtext("String", "")
        if len(rows) >= 256:
            raise ValueError("Too many metadata fields; use a narrower manual workflow")
        rows.append(
            {
                "name": name[:100],
                "value": value[:1000],
                "editable": bool(re.fullmatch(r"[A-Za-z0-9_. -]{1,100}", name)),
                "identity": name.upper() in {"IMDB", "TMDB", "IMDB_ID", "TMDB_ID"},
                "editable_value": id(node) in editable_nodes and bool(re.fullmatch(r"[A-Z][A-Z0-9_]{0,99}", name)) and name not in reserved,
                "scope": "global" if id(node) in editable_nodes else "targeted/nested",
            }
        )
    return rows


def attachment_signature(item):
    return (item.get("file_name"), item.get("content_type"), item.get("size"), item.get("description", ""))


def verify_selection(source, result, options, tags, imdb, tmdb, extra_tags=None):
    options = cleanup_options(options)
    kept = [item for item in source.get("attachments", []) if str(item["id"]) not in options["remove_attachment_ids"]]
    actual = result.get("attachments", [])
    if [attachment_signature(item) for item in kept] != [attachment_signature(item) for item in actual]:
        raise ValueError("Preserved attachments/fonts changed or removal failed")
    props = result.get("container", {}).get("properties", {})
    if options["container_title"] is not None and props.get("title", "") != options["container_title"]:
        raise ValueError("Requested container title was not applied")
    if options["clear_title"] and props.get("title"):
        raise ValueError("Selected container title was not removed")
    if options["remove_dates"] and (props.get("date_utc") or props.get("date_local")):
        raise ValueError("Selected mux date was not removed")
    for track in result.get("tracks", []):
        name = track.get("properties", {}).get("track_name", "")
        edit = options["track_overrides"].get(str(track["id"]), {})
        if "name" in edit and name != edit["name"]:
            raise ValueError("Requested track name was not applied")
        if str(track["id"]) in options["remove_track_names"] and name:
            raise ValueError("Selected track name was not removed")
        if "cardinaldl" in name.casefold():
            raise ValueError("CardinalDL track branding survived")
    rows = readable_tags(tags)
    values = {(r["name"].upper(), r["value"]) for r in rows}
    expected = {("IMDB", imdb), ("TMDB", str(tmdb)), *{**(extra_tags or {}), **options["tag_edits"]}.items()}
    if not expected.issubset(values):
        raise ValueError("Requested identity or editable tags were not verified")
    if any(r["name"].upper() in options["remove_tag_names"] and r["name"].upper() not in {"IMDB", "TMDB", *(extra_tags or {}), *options["tag_edits"]} for r in rows):
        raise ValueError("Selected metadata tag survived")

"""Allowlist-based Matroska metadata sanitization; no anonymity guarantees."""

from __future__ import annotations

import re
import secrets
import xml.etree.ElementTree as ET


class PrivacyError(ValueError):
    """An output still contains unsupported or identifying container metadata."""


def sanitized_chapters(xml: str) -> bytes:
    xml = re.sub(r"""<!DOCTYPE\s+Chapters\s+SYSTEM\s+["']matroskachapters\.dtd["']\s*>""", "", xml, flags=re.I)
    if len(xml) > 4 * 1024 * 1024 or "<!ENTITY" in xml.upper() or "<!DOCTYPE" in xml.upper():
        raise PrivacyError("Unsupported chapters document")
    try:
        source = ET.fromstring(xml)
    except ET.ParseError:
        raise PrivacyError("Invalid chapters document") from None
    if source.tag != "Chapters":
        raise PrivacyError("Invalid chapters root")
    root = ET.Element("Chapters")
    count = 0

    def atom(old, parent, depth=0):
        nonlocal count
        if depth > 20 or count >= 10000:
            raise PrivacyError("Chapter structure exceeds safe bounds")
        # Ordered/linked editions can refer to other private segment identities.
        if old.find("ChapterSegmentUID") is not None:
            raise PrivacyError("Linked chapters require explicit manual review")
        start = old.findtext("ChapterTimeStart")
        if not start or not re.fullmatch(r"[0-9]{2,}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?", start):
            raise PrivacyError("Chapter start is invalid")
        new = ET.SubElement(parent, "ChapterAtom")
        ET.SubElement(new, "ChapterUID").text = str(secrets.randbits(63) + 1)
        for key in ["ChapterTimeStart", "ChapterTimeEnd", "ChapterFlagHidden", "ChapterFlagEnabled"]:
            value = old.findtext(key)
            if value is not None:
                if key.startswith("ChapterTime") and not re.fullmatch(r"[0-9]{2,}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?", value):
                    raise PrivacyError("Chapter time is invalid")
                if key.startswith("ChapterFlag") and value not in {"0", "1"}:
                    raise PrivacyError("Chapter flag is invalid")
                ET.SubElement(new, key).text = value
        count += 1
        display = ET.SubElement(new, "ChapterDisplay")
        ET.SubElement(display, "ChapterString").text = f"Chapter {count:02}"
        ET.SubElement(display, "ChapterLanguage").text = "eng"
        for child in old.findall("ChapterAtom"):
            atom(child, new, depth + 1)

    for edition in source.findall("EditionEntry"):
        if edition.findtext("EditionFlagOrdered") == "1":
            raise PrivacyError("Ordered chapters require manual review")
        new = ET.SubElement(root, "EditionEntry")
        ET.SubElement(new, "EditionUID").text = str(secrets.randbits(63) + 1)
        for chapter in edition.findall("ChapterAtom"):
            atom(chapter, new)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def safe_track_name(track: dict, language: str) -> str:
    properties = track.get("properties", {})
    parts = [language]
    if properties.get("forced_track"):
        parts.append("Forced")
    if properties.get("flag_hearing_impaired") or properties.get("hearing_impaired"):
        parts.append("SDH")
    if properties.get("flag_commentary"):
        parts.append("Commentary")
    return " ".join(parts)


def verify_privacy(source: dict, result: dict, tags: str, imdb: str, tmdb: int, track_names: dict, extra_tags=None) -> None:
    properties = result.get("container", {}).get("properties", {})
    if any(properties.get(key) not in (None, "", []) for key in ["date_utc", "date_local", "segment_filename", "previous_segment_uid", "next_segment_uid", "segment_family"]):
        raise PrivacyError("Identifying date or segment linkage remains")
    if result.get("attachments"):
        raise PrivacyError("Attachments may contain private embedded metadata")
    previous = source.get("container", {}).get("properties", {}).get("segment_uid")
    current = properties.get("segment_uid")
    if not current or current == previous:
        raise PrivacyError("Segment identity was not regenerated")
    try:
        root = ET.fromstring(tags)
    except ET.ParseError:
        raise PrivacyError("Invalid output identity tags") from None
    expected = {("IMDB", imdb), ("TMDB", str(tmdb)), *(extra_tags or {}).items()}
    simples = list(root.iter("Simple"))
    actual = {(node.findtext("Name"), node.findtext("String")) for node in simples}
    if actual != expected or len(simples) != len(expected):
        raise PrivacyError("Unexpected release tags survived privacy sanitization")
    if any(node.tag not in {"Tags", "Tag", "Targets", "Simple", "Name", "String", "TagLanguage", "TagLanguageIETF", "DefaultLanguage"} for node in root.iter()):
        raise PrivacyError("Unexpected private tag targets/fields survived")
    for old, new in zip(source.get("tracks", []), result.get("tracks", []), strict=True):
        a, b = old.get("properties", {}), new.get("properties", {})
        if a.get("uid") is not None and a.get("uid") == b.get("uid"):
            raise PrivacyError("Track identity was not regenerated")
        if b.get("track_name", "") != track_names[str(old["id"])]:
            raise PrivacyError("An original track title survived sanitization")

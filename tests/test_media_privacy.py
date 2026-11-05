# ruff: noqa: S101
"""Keep only public identity metadata; preserve chapters' timing, not private labels."""

import xml.etree.ElementTree as ET

import pytest

from src.media_privacy import PrivacyError, sanitized_chapters, verify_privacy


def test_private_chapters_keep_timing_not_names_or_uids():
    source = "<Chapters><EditionEntry><EditionUID>123</EditionUID><ChapterAtom><ChapterUID>456</ChapterUID><ChapterTimeStart>00:00:00.000000000</ChapterTimeStart><ChapterTimeEnd>00:00:01.000000000</ChapterTimeEnd><ChapterDisplay><ChapterString>email@example.test workstation device-id</ChapterString></ChapterDisplay></ChapterAtom></EditionEntry></Chapters>"
    output = sanitized_chapters(source)
    root = ET.fromstring(output)
    assert root.findtext(".//ChapterTimeEnd") == "00:00:01.000000000"
    assert root.findtext(".//ChapterString") == "Chapter 01"
    assert root.findtext(".//ChapterUID") != "456" and root.findtext(".//EditionUID") != "123"
    assert b"email" not in output and b"workstation" not in output


@pytest.mark.parametrize(
    "xml",
    [
        '<!DOCTYPE Chapters [<!ENTITY x SYSTEM "file:///etc/passwd">]><Chapters/>',
        "<Chapters><EditionEntry><EditionFlagOrdered>1</EditionFlagOrdered></EditionEntry></Chapters>",
        "<Chapters><EditionEntry><ChapterAtom><ChapterSegmentUID>private</ChapterSegmentUID></ChapterAtom></EditionEntry></Chapters>",
    ],
)
def test_unsafe_chapters_fail_closed(xml):
    with pytest.raises(PrivacyError):
        sanitized_chapters(xml)


def document(uid=1):
    return {"container": {"properties": {"segment_uid": "new"}}, "tracks": [{"id": 0, "properties": {"uid": uid, "track_name": "en"}}]}


@pytest.mark.parametrize("fault", ["date", "attachment", "old_uid", "track_title", "extra_tag", "source_segment"])
def test_output_privacy_leaks_fail_verification(fault):
    source = document(1)
    source["container"]["properties"]["segment_uid"] = "old"
    result = document(2)
    tags = "<Tags><Tag><Targets/><Simple><Name>IMDB</Name><String>tt1234567</String></Simple><Simple><Name>TMDB</Name><String>42</String></Simple></Tag></Tags>"
    if fault == "date":
        result["container"]["properties"]["date_utc"] = "2026-01-01"
    elif fault == "attachment":
        result["attachments"] = [{"file_name": "device-photo.jpg"}]
    elif fault == "old_uid":
        result["tracks"][0]["properties"]["uid"] = 1
    elif fault == "track_title":
        result["tracks"][0]["properties"]["track_name"] = "user@workstation"
    elif fault == "source_segment":
        result["container"]["properties"]["segment_uid"] = "old"
    else:
        tags = tags.replace("</Tag>", "<Simple><Name>COMMENT</Name><String>user@workstation</String></Simple></Tag>")
    with pytest.raises(PrivacyError):
        verify_privacy(source, result, tags, "tt1234567", 42, {"0": "en"})


def test_privacy_clean_output_is_accepted():
    source = document(1)
    source["container"]["properties"]["segment_uid"] = "old"
    tags = "<Tags><Tag><Targets/><Simple><Name>IMDB</Name><String>tt1234567</String></Simple><Simple><Name>TMDB</Name><String>42</String></Simple></Tag></Tags>"
    verify_privacy(source, document(2), tags, "tt1234567", 42, {"0": "en"})

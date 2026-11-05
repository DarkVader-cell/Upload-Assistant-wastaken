# ruff: noqa: S101

import xml.etree.ElementTree as ET

import pytest

from src.catalogue_media import cleaned_tags
from src.media_selection import cleanup_options, readable_tags, verify_selection
from src.media_template import validate_options


def test_gui_edits_validated_without_allowing_technical_fact_spoofing():
    data = cleanup_options(
        {
            "container_title": "Reviewed title",
            "track_overrides": {"1": {"name": "Tamil 5.1", "language": "ta", "default": True, "forced": False}},
            "tag_edits": {"ARTIST": "Reviewed creator", "MY_NOTE": "Approved"},
        }
    )
    assert data["track_overrides"]["1"]["language"] == "ta"
    for invalid in [
        {"track_overrides": {"1": {"codec": "HEVC"}}},
        {"track_overrides": {"1": {"default": "yes"}}},
        {"clear_title": True, "container_title": "Conflicting"},
        {"track_overrides": {"../": {"name": "Bad"}}},
    ]:
        with pytest.raises(ValueError):
            cleanup_options(invalid)
    for field in ["ENCODER", "WRITING_APPLICATION", "DURATION", "WIDTH", "IMDB"]:
        with pytest.raises(ValueError):
            validate_options(tags={field: "fake"})


def test_global_edit_preserves_targeted_tag_with_same_name():
    source = "<Tags><Tag><Targets/><Simple><Name>GENRE</Name><String>Old global</String></Simple></Tag><Tag><Targets><TrackUID>123</TrackUID></Targets><Simple><Name>GENRE</Name><String>Retained track metadata</String></Simple></Tag></Tags>"
    output = cleaned_tags(source, "tt1234567", 42, {"GENRE": "New global"})
    rows = readable_tags(output.decode())
    assert any(r["value"] == "New global" and r["scope"] == "global" for r in rows)
    assert any(r["value"] == "Retained track metadata" and not r["editable_value"] for r in rows)
    assert b"Old global" not in output
    assert all(tag.findall('Simple') for tag in ET.fromstring(output).findall('Tag'))


def test_removing_last_targeted_value_drops_invalid_empty_tag():
    source='<Tags><Tag><Targets><TrackUID>123</TrackUID></Targets><Simple><Name>COMMENT</Name><String>Selected private note</String></Simple></Tag></Tags>'
    result=ET.fromstring(cleaned_tags(source,'tt1234567',42,remove_names=['COMMENT']))
    assert len(result.findall('Tag'))==1
    assert all(tag.findall('Simple')for tag in result.findall('Tag'))
    assert b'Selected private note'not in ET.tostring(result)


def test_metadata_write_verification_requires_requested_values():
    source = {"tracks": [{"id": 1, "properties": {"track_name": "Old"}}], "attachments": []}
    result = {"tracks": [{"id": 1, "properties": {"track_name": "New"}}], "attachments": [], "container": {"properties": {"title": "Reviewed title"}}}
    options = {"container_title": "Reviewed title", "track_overrides": {"1": {"name": "New"}}, "tag_edits": {"MY_NOTE": "Reviewed"}}
    tags = cleaned_tags("", "tt1234567", 42, {"MY_NOTE": "Reviewed"}).decode()
    verify_selection(source, result, options, tags, "tt1234567", 42)
    result["tracks"][0]["properties"]["track_name"] = "Not applied"
    with pytest.raises(ValueError):
        verify_selection(source, result, options, tags, "tt1234567", 42)

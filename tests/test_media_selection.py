# ruff: noqa: S101
import copy

import pytest

from src.catalogue_media import cleaned_tags, process_media
from src.media_selection import cleanup_options, readable_tags, verify_selection

FONT = {"id": 1, "file_name": "subtitle-font.ttf", "content_type": "font/ttf", "size": 128, "description": "Subtitle font"}


def test_selective_defaults_preserve_fonts_and_metadata():
    opts = cleanup_options({})
    assert opts["remove_attachment_ids"] == [] and opts["remove_tag_names"] == []
    assert not opts["clear_title"] and not opts["clear_chapter_names"]


def test_only_selected_tags_removed_branding_always_removed():
    xml = "<Tags><Tag><Targets/><Simple><Name>COMMENT</Name><String>private email</String></Simple><Simple><Name>GENRE</Name><String>Drama</String></Simple><Simple><Name>ENCODER</Name><String>CardinalDL</String></Simple></Tag></Tags>"
    output = cleaned_tags(xml, "tt1234567", 42, remove_names=["COMMENT"])
    rows = readable_tags(output.decode())
    assert "COMMENT" not in {r["name"] for r in rows} and "ENCODER" not in {r["name"] for r in rows}
    assert ("GENRE", "Drama") in {(r["name"], r["value"]) for r in rows}


def test_font_preservation_verified_and_unselected_fields_allowed():
    source = {"attachments": [FONT], "tracks": []}
    result = copy.deepcopy(source)
    result["container"] = {"properties": {"writing_application": "mkvmerge v74", "title": "Retained movie title"}}
    tags = cleaned_tags("<Tags><Tag><Targets/><Simple><Name>GENRE</Name><String>Drama</String></Simple></Tag></Tags>", "tt1234567", 42).decode()
    verify_selection(source, result, {}, tags, "tt1234567", 42)
    result["attachments"] = []
    with pytest.raises(ValueError):
        verify_selection(source, result, {}, tags, "tt1234567", 42)


def test_selected_title_and_tag_cannot_silently_survive():
    source = {"attachments": [FONT], "tracks": []}
    result = copy.deepcopy(source)
    result["container"] = {"properties": {"title": "Private title"}}
    tags = cleaned_tags("", "tt1234567", 42).decode()
    with pytest.raises(ValueError):
        verify_selection(source, result, {"clear_title": True}, tags, "tt1234567", 42)


@pytest.mark.parametrize("value", [{"remove_attachment_ids": ["1;rm -rf"]}, {"clear_title": "yes"}, {"remove_tag_names": ["../../secret"]}, {"unknown_flag": True}])
def test_invalid_gui_choices_fail_closed(value):
    with pytest.raises(ValueError):
        cleanup_options(value)


def test_font_kept_dry_preview_writes_nothing(tmp_path, monkeypatch):
    source = tmp_path / "file.mkv"
    source.write_bytes(b"fixture")
    monkeypatch.setattr(
        "src.catalogue_media._identify",
        lambda _path: {"attachments": [FONT], "tracks": [{"id": 0, "type": "video", "properties": {}}, {"id": 1, "type": "audio", "properties": {}}]},
    )
    result = process_media(tmp_path, source, tmp_path / "output.mkv", "tt1234567", 42, cleanup={})
    assert result["attachments_to_remove"] == 0 and result["cleanup_mode"] == "selected" and not result["executed"]
    assert not (tmp_path / "output.mkv").exists()

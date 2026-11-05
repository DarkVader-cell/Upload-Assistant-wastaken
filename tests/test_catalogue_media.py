# ruff: noqa: S101
"""Post-processing never mutates existing payloads or invents language/IDs."""

import os
import xml.etree.ElementTree as ET

import pytest

from src.catalogue_media import MediaError, cleaned_tags, language_code, process_media


@pytest.mark.parametrize(("original", "expected"), [("eng", "en"), ("tam", "ta"), ("pt_BR", "pt-BR"), ("zho-Hans", "zh-Hans"), ("es-419", "es-419"), ("und", "und")])
def test_subtitle_code_normalization(original, expected):
    assert language_code(original) == expected


@pytest.mark.parametrize("code", ["English", "en;rm -rf", "xyz", "en-", ""])
def test_no_guessed_languages(code):
    with pytest.raises(MediaError):
        language_code(code)


def test_tags_preserve_useful_metadata_but_replace_branding_and_ids():
    tags = "<Tags><Tag><Targets/><Simple><Name>TITLE</Name><String>Actual movie</String></Simple><Simple><Name>ENCODER</Name><String>CardinalDL</String></Simple><Simple><Name>IMDB</Name><String>wrong</String></Simple></Tag></Tags>"
    result = cleaned_tags(tags, "tt1234567", 42)
    root = ET.fromstring(result)
    assert b"CardinalDL" not in result and b"wrong" not in result
    assert {(x.findtext("Name"), x.findtext("String")) for x in root.iter("Simple")} == {("TITLE", "Actual movie"), ("IMDB", "tt1234567"), ("TMDB", "42")}


@pytest.mark.parametrize("xml", ['<!DOCTYPE Tags [<!ENTITY secret SYSTEM "file:///etc/passwd">]><Tags/>', "<Wrong/>", "<Tags>"])
def test_unsafe_or_malformed_tags_refused(xml):
    with pytest.raises(MediaError):
        cleaned_tags(xml, "tt1234567", 42)


def test_hardlinks_symlinks_and_overwrite_refused_before_tools(tmp_path):
    root = tmp_path / "job"
    root.mkdir(mode=0o700)
    source = root / "movie.mkv"
    source.write_bytes(b"original")
    output = root / "out.mkv"
    os.link(source, root / "linked.mkv")
    with pytest.raises(MediaError):
        process_media(root, source, output, "tt1234567", 42)
    (root / "linked.mkv").unlink()
    (root / "symbolic.mkv").symlink_to(source)
    with pytest.raises(MediaError):
        process_media(root, root / "symbolic.mkv", output, "tt1234567", 42)
    with pytest.raises(MediaError):
        process_media(root, source, source, "tt1234567", 42)
    with pytest.raises(MediaError):
        process_media(root, source, root / ".." / "escaped.mkv", "tt1234567", 42)
    assert source.read_bytes() == b"original"


def test_dry_plan_does_not_write_or_remux(tmp_path, monkeypatch):
    root = tmp_path / "job"
    root.mkdir(mode=0o700)
    source = root / "movie.mkv"
    source.write_bytes(b"original")
    output = root / "new.mkv"
    from src import catalogue_media as module

    monkeypatch.setattr(
        module,
        "_identify",
        lambda _path: {
            "tracks": [
                {"id": 0, "type": "video", "properties": {}},
                {"id": 1, "type": "audio", "properties": {}},
                {"id": 2, "type": "subtitles", "properties": {"language": "tam", "forced_track": True}},
            ]
        },
    )
    result = process_media(root, source, output, "tt1234567", 42)
    assert result["subtitle_languages"] == {"2": "ta"} and not result["executed"] and result["original_retained"]
    assert not output.exists() and source.read_bytes() == b"original"


def test_unknown_subtitle_track_mapping_refused(tmp_path, monkeypatch):
    root = tmp_path / "job"
    root.mkdir(mode=0o700)
    source = root / "movie.mkv"
    source.write_bytes(b"original")
    from src import catalogue_media as module

    monkeypatch.setattr(module, "_identify", lambda _path: {"tracks": [{"id": 0, "type": "video", "properties": {}}, {"id": 1, "type": "audio", "properties": {}}]})
    with pytest.raises(MediaError):
        process_media(root, source, root / "new.mkv", "tt1234567", 42, {"0": "en"})

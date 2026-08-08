import asyncio

from src.get_name import NameManager
from src.meta import Meta
from src.trackers.UNIT3D.skipthecommercials import SkipTheCommercials


def test_stc_places_aka_and_language_after_series_title_and_season():
    meta = Meta(
        category="TV",
        type="WEBDL",
        title="TMDB Title",
        aka="AKA Other Title",
        season="S01",
        episode="E02",
        audio_languages=["English"],
        trackers=["SKIPTHECOMMERCIALS"],
        source="WEB",
        service="Example",
        resolution="1080p",
        audio="DDP 5.1",
        video_encode="x265",
    )

    name, *_ = asyncio.run(NameManager({"DEFAULT": {}}).get_name(meta))

    assert name.startswith("TMDB Title AKA Other Title S01E02")  # noqa: S101
    assert "MULTI" not in name  # noqa: S101


def test_stc_adds_multi_only_to_its_tracker_name():
    meta = Meta(
        category="TV",
        type="WEBDL",
        title="TMDB Title",
        season="S01",
        episode="E02",
        audio_languages=["English", "Japanese"],
        trackers=["SKIPTHECOMMERCIALS", "ONLYENCODES"],
        source="WEB",
        service="Example",
        resolution="1080p",
        audio="DDP 5.1",
        video_encode="x265",
    )
    base_name, *_ = asyncio.run(NameManager({"DEFAULT": {}}).get_name(meta))
    stc_name = asyncio.run(SkipTheCommercials({"DEFAULT": {}}).get_name(meta))["name"]

    assert "MULTI" not in base_name  # noqa: S101
    assert "S01E02 MULTI" in stc_name  # noqa: S101


def test_stc_does_not_duplicate_dual_audio_as_multi():
    meta = Meta(
        category="TV",
        type="WEBDL",
        title="ODD TAXI",
        season="S01",
        episode="E01",
        audio_languages=["English", "Japanese"],
        dual_audio=True,
        trackers=["SKIPTHECOMMERCIALS", "ONLYENCODES"],
        source="WEB",
        service="CR",
        resolution="1080p",
        audio="Dual-Audio FLAC 2.0",
        video_encode="H.264",
    )
    stc_name = asyncio.run(SkipTheCommercials({"DEFAULT": {}}).get_name(meta))["name"]

    assert "MULTI" not in stc_name  # noqa: S101
    assert "Dual-Audio FLAC 2.0" in stc_name  # noqa: S101


def test_stc_omits_english_language_tag():
    meta = Meta(category="TV", type="WEBDL", title="TMDB Title", season="S01", episode="E01", audio_languages=["English"], trackers=["SKIPTHECOMMERCIALS"])

    name, *_ = asyncio.run(NameManager({"DEFAULT": {}}).get_name(meta))

    assert "S01E01 English" not in name  # noqa: S101


def test_identical_aka_is_omitted():
    meta = Meta(category="TV", type="WEBDL", title="TMDB Title", aka="AKA TMDB Title", season="S01", episode="E01")

    name, *_ = asyncio.run(NameManager({"DEFAULT": {}}).get_name(meta))

    assert "AKA" not in name  # noqa: S101

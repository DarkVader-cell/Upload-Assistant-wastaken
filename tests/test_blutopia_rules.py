# ruff: noqa: S101

import asyncio
from types import SimpleNamespace

import pytest

from src.meta import Meta
from src.trackers.UNIT3D.blutopia import Blutopia
from src.trackers.UNIT3D.ulcx import ULCX


def make_meta(**overrides):
    values = {
        "type": "ENCODE",
        "resolution": "1080p",
        "container": "mkv",
        "is_disc": "",
        "hdr": "",
        "tag": "",
        "unattended": True,
        "unattended_confirm": False,
        "valid_mi_settings": True,
        "tracker_status": {"BLUTOPIA": {}},
        "mediainfo": {"media": {"track": []}},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def tracker() -> Blutopia:
    instance = object.__new__(Blutopia)
    instance.tracker = "BLUTOPIA"
    return instance


def audio(format_name: str) -> dict[str, str]:
    return {"@type": "Audio", "Format": format_name}


def test_blutopia_rejects_opus_in_encodes():
    meta = make_meta(mediainfo={"media": {"track": [audio("Opus")]}})
    assert asyncio.run(tracker().get_additional_checks(meta)) is False


def test_blutopia_rejects_sd_encodes():
    meta = make_meta(resolution="576p")
    assert asyncio.run(tracker().get_additional_checks(meta)) is False


def test_blutopia_requires_ac3_for_each_truehd_track():
    meta = make_meta(mediainfo={"media": {"track": [audio("TrueHD")]}})
    assert asyncio.run(tracker().get_additional_checks(meta)) is False


def test_blutopia_accepts_truehd_with_standalone_ac3():
    meta = make_meta(mediainfo={"media": {"track": [audio("TrueHD"), audio("AC-3")]}})
    assert asyncio.run(tracker().get_additional_checks(meta)) is True


def test_blutopia_uses_tmdb_title_and_year_before_the_alternate_title():
    meta = Meta(
        category="MOVIE",
        title="TMDb Title",
        aka="AKA Other Title",
        name="AKA Other Title TMDb Title 2025 1080p WEB-DL-GRP",
        year=2026,
        imdb_info={"title": "IMDb Display Title", "aka": "IMDb Original Title", "year": 2025},
        tracker_status={"BLUTOPIA": {}},
    )

    name = asyncio.run(tracker().get_name(meta))["name"]

    assert name == "TMDb Title AKA Other Title 2026 1080p WEB-DL-GRP"


@pytest.mark.parametrize(
    ("adapter", "tracker_name", "expected_year"),
    [
        (tracker(), "BLUTOPIA", "2026"),
        (object.__new__(ULCX), "ULCX", "2025"),
    ],
)
def test_unit3d_tracker_year_precedence(adapter, tracker_name, expected_year):
    adapter.tracker = tracker_name
    name = "Pagida Kali 2026 1080p SS WEB-DL DD+ 5.1 H.264-SH3LBY"
    meta = Meta(
        category="MOVIE",
        type="WEBDL",
        title="Pagida Kali",
        name=name,
        year=2026,
        resolution="1080p",
        imdb_info={"title": "Pagida Kali", "aka": "Pagida Kali", "year": 2025},
        tracker_status={tracker_name: {}},
    )

    expected_name = name.replace("2026", expected_year, 1)
    assert asyncio.run(adapter.get_name(meta))["name"] == expected_name

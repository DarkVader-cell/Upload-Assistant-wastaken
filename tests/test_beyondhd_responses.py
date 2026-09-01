# ruff: noqa: S101

import asyncio

from src.meta import Meta
from src.trackerhandle import should_inject_uploaded_torrent
from src.trackers.beyondhd import BEYONDHD, format_bhd_imdb_id


def test_beyondhd_imdb_ids_are_zero_padded_or_use_the_no_id_sentinel() -> None:
    assert format_bhd_imdb_id(12345) == "0012345"
    assert format_bhd_imdb_id("tt1234567") == "1234567"
    assert format_bhd_imdb_id(None) == "0"


def test_beyondhd_drafts_are_injected_while_other_drafts_wait_for_publication() -> None:
    draft_status = {"pending_publication": True}

    assert should_inject_uploaded_torrent("BEYONDHD", draft_status, is_usenet=False)
    assert not should_inject_uploaded_torrent("LST", draft_status, is_usenet=False)
    assert should_inject_uploaded_torrent("BEYONDHD", {}, is_usenet=False)
    assert not should_inject_uploaded_torrent("BEYONDHD", {}, is_usenet=True)


def test_beyondhd_uses_imdb_title_before_its_aka() -> None:
    meta = Meta(
        name="Local Title AKA IMDb Display 2026 1080p WEB-DL-GRP",
        title="Local Title",
        aka="AKA IMDb Display",
        imdb_info={"title": "IMDb Display", "aka": "Original Title"},
    )

    name = asyncio.run(BEYONDHD({"TRACKERS": {"BEYONDHD": {}}}).get_name(meta))

    assert name == "IMDb Display AKA Original Title 2026 1080p WEB-DL-GRP"


def test_beyondhd_omits_aka_already_present_in_tmdb_metadata() -> None:
    meta = Meta(
        name="Localized Title AKA Original Title 2026 1080p WEB-DL-GRP",
        title="Localized Title",
        original_title="Original Title",
        aka="AKA Original Title",
        imdb_info={"title": "IMDb Display", "aka": "Original Title"},
    )

    name = asyncio.run(BEYONDHD({"TRACKERS": {"BEYONDHD": {}}}).get_name(meta))

    assert name == "IMDb Display 2026 1080p WEB-DL-GRP"


def test_beyondhd_maps_480i_to_other_category() -> None:
    meta = Meta(type="ENCODE", resolution="480i")

    assert asyncio.run(BEYONDHD({"TRACKERS": {"BEYONDHD": {}}}).get_type(meta)) == "Other"

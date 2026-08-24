# ruff: noqa: S101

from src.trackerhandle import should_inject_uploaded_torrent
from src.trackers.beyondhd import format_bhd_imdb_id


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

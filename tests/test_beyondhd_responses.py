# ruff: noqa: S101

from src.trackers.beyondhd import format_bhd_imdb_id


def test_beyondhd_imdb_ids_are_zero_padded_or_use_the_no_id_sentinel() -> None:
    assert format_bhd_imdb_id(12345) == "0012345"
    assert format_bhd_imdb_id("tt1234567") == "1234567"
    assert format_bhd_imdb_id(None) == "0"

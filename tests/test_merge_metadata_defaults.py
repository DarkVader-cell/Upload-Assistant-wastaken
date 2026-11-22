# ruff: noqa: S101
from src.meta import Meta


def test_legacy_tracker_metadata_defaults_are_safe_and_independent():
    first = Meta()
    second = Meta()
    assert first.were_trumping is False
    assert first.trump_reason is None
    assert first.trumpable_id is None
    assert first.season_pack_contains_episode is None
    assert first.screenshots_reported_torrent is None
    assert first.screenshots_trumping_torrent is None
    first.skip_upload_trackers.append("AITHER")
    assert second.skip_upload_trackers == []

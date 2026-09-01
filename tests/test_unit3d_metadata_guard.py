from src.meta import Meta
from src.trackers.common import Common


def test_unit3d_result_rejects_unrelated_release_title() -> None:
    meta = Meta(regex_title="12 Years a Slave", filename="12 Years a Slave")

    assert not Common._unit3d_result_matches_source(meta, {"name": "Bitter Harvest 1993 1080p BluRay"})  # noqa: S101


def test_unit3d_result_accepts_matching_release_title() -> None:
    meta = Meta(regex_title="12 Years a Slave", filename="12 Years a Slave")

    assert Common._unit3d_result_matches_source(meta, {"name": "12 Years a Slave 2013 1080p BluRay"})  # noqa: S101

# ruff: noqa: S101

import asyncio

from src.dupe_checking import DupeChecker, has_non_disc_candidate_evidence, is_full_disc_candidate
from src.meta import Meta
from src.trackers.hdbits import _hdb_dupe_entry


def test_structured_disc_candidate_detection_uses_container_and_type() -> None:
    assert is_full_disc_candidate({"type": "BluRay Raw"})
    assert is_full_disc_candidate({"container": "M2TS"})
    assert is_full_disc_candidate({"container": "ISO", "source": "UHD BluRay"})
    assert not is_full_disc_candidate({"type": "BluRay", "container": "MKV"})
    assert has_non_disc_candidate_evidence({"type": "REMUX"})


def test_full_disc_candidate_with_partial_file_count_remains_a_dupe() -> None:
    meta = Meta(category="MOVIE", is_disc="BDMV", name="Movie 2026 1080p BluRay", uuid="Movie", resolution="1080p")
    candidate = {"name": "Movie 2026 1080p BluRay", "type": "DISC", "container": "BDMV", "file_count": 1}

    results = asyncio.run(DupeChecker({"DEFAULT": {}}).filter_dupes([candidate], meta, "ANTHELION"))

    assert [item["name"] for item in results] == [candidate["name"]]


def test_structured_encode_is_not_treated_as_existing_full_disc() -> None:
    meta = Meta(category="MOVIE", is_disc="BDMV", name="Movie 2026 1080p BluRay", uuid="Movie", resolution="1080p")
    candidate = {"name": "Movie 2026 1080p BluRay x264", "type": "ENCODE", "container": "MKV", "file_count": 1}

    assert asyncio.run(DupeChecker({"DEFAULT": {}}).filter_dupes([candidate], meta, "ANTHELION")) == []


def test_hdb_candidate_projection_preserves_disc_evidence() -> None:
    result = _hdb_dupe_entry(
        {
            "id": 123,
            "name": "Movie",
            "filename": "Movie.torrent",
            "size": 10,
            "numfiles": 1,
            "category": 1,
            "medium": 1,
            "codec": 5,
            "container": "M2TS",
            "resolution": "1080p",
            "tags": "HDR10, Internal",
            "origin": 1,
        },
        "https://hdbits.org",
        "secret",
    )

    assert result["type"] == "DISC"
    assert result["container"] == "M2TS"
    assert result["file_count"] == 1
    assert result["codec"] == "H.265"
    assert result["flags"] == ["HDR10", "Internal"]

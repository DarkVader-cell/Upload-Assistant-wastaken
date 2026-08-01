import asyncio

from src.get_name import NameManager
from src.meta import Meta


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

    assert name.startswith("TMDB Title AKA Other Title S01E02 English")  # noqa: S101

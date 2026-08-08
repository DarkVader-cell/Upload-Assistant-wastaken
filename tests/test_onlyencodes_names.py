import asyncio

from src.meta import Meta
from src.trackers.UNIT3D.onlyencodes import OnlyEncodes


def test_onlyencodes_uses_tmdb_title_instead_of_imdb_display_title():
    meta = Meta(
        category="MOVIE",
        type="WEBDL",
        title="ODDTAXI in the Woods",
        year=2022,
        name="ODDTAXI in the Woods 2022 1080p CR WEB-DL DD+ 2.0 H.264-Kitsune",
        imdb_info={"title": "Eiga Odd Taxi: In the Woods", "year": "2022"},
        audio_languages=["English"],
        resolution="1080p",
        source="CR",
        service="CR",
        audio="DD+ 2.0",
        video_encode="H.264",
        tag="Kitsune",
    )

    name = asyncio.run(OnlyEncodes({"DEFAULT": {}, "TRACKERS": {}}).get_name(meta))["name"]

    assert name.startswith("ODDTAXI in the Woods 2022")  # noqa: S101
    assert "Eiga Odd Taxi" not in name  # noqa: S101

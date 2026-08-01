import pytest

from src.meta import Meta
from src.trackers.UNIT3D.torrentdesi import DesiTorrents
from src.trackers.UNIT3D.torrentdesi import INDIAN_LANGUAGES


def test_torrentdesi_indian_language_list_contains_required_aliases() -> None:
    languages = set(INDIAN_LANGUAGES)
    assert {"hindi", "hin", "hi", "bengali", "bangla", "bn", "punjabi", "panjabi", "odia", "oriya"} <= languages


@pytest.mark.asyncio
async def test_torrentdesi_does_not_bypass_language_check_for_bdmv() -> None:
    calls: list[dict[str, object]] = []

    class FakeCommon:
        async def check_language_requirements(self, meta, tracker, **kwargs):
            calls.append({"meta": meta, "tracker": tracker, **kwargs})
            return False

    tracker = object.__new__(DesiTorrents)
    tracker.common = FakeCommon()
    meta = Meta({"category": "MOVIE", "is_disc": "BDMV"})

    assert await tracker.get_additional_checks(meta) is False
    assert calls and calls[0]["check_audio"] is True

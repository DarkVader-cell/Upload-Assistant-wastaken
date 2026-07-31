"""Regression tests for streaming-service aliases and filename recognition."""

import asyncio

from src import region


def test_indian_streaming_aliases_are_exposed_with_uppercase_codes():
    services = asyncio.run(region.get_service(get_services_only=True))

    expected = {
        "Sun NXT": "SNXT",
        "Tentkotta": "TK",
        "GooglePlay": "GPLAY",
        "Voot": "VOOT",
        "Disney+ Hotstar": "DSPH",
        "JioHotstar": "JHS",
        "ZEE 5": "ZEE5",
        "JioCinema": "JC",
        "SimplySouth": "SS",
        "ChaupalTV": "CHTV",
        "Manorama MAX": "MMAX",
        "Discovery+": "DSCV",
    }

    assert {key: services[key] for key in expected} == expected  # noqa: S101


def test_sonyliv_filename_detection_ignores_separators_and_case(monkeypatch):
    def fake_guessit(_value, _options=None):
        return {"title": "Example"}

    monkeypatch.setattr(region, "_guessit_fn", fake_guessit)

    for filename in ("Example.SonyLIV.1080p.mkv", "Example_sOnY-lIv_1080p.mkv", "ExampleSONYLIV1080p.mkv"):
        service, _ = asyncio.run(region.get_service(filename))
        assert service == "SONY"  # noqa: S101


def test_existing_lowercase_i_service_codes_remain_unchanged():
    services = asyncio.run(region.get_service(get_services_only=True))

    assert services["BBC iPlayer"] == "iP"  # noqa: S101
    assert services["iTunes"] == "iT"  # noqa: S101
    assert services["iQIYI"] == "iQIYI"  # noqa: S101

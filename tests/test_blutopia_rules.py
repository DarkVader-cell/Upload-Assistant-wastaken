import asyncio
from types import SimpleNamespace

from src.trackers.UNIT3D.blutopia import Blutopia


def make_meta(**overrides):
    values = {
        "type": "ENCODE",
        "resolution": "1080p",
        "container": "mkv",
        "is_disc": "",
        "hdr": "",
        "tag": "",
        "unattended": True,
        "unattended_confirm": False,
        "valid_mi_settings": True,
        "tracker_status": {"BLUTOPIA": {}},
        "mediainfo": {"media": {"track": []}},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def tracker() -> Blutopia:
    instance = object.__new__(Blutopia)
    instance.tracker = "BLUTOPIA"
    return instance


def audio(format_name: str) -> dict[str, str]:
    return {"@type": "Audio", "Format": format_name}


def test_blutopia_rejects_opus_in_encodes():
    meta = make_meta(mediainfo={"media": {"track": [audio("Opus")]}})
    assert asyncio.run(tracker().get_additional_checks(meta)) is False


def test_blutopia_rejects_sd_encodes():
    meta = make_meta(resolution="576p")
    assert asyncio.run(tracker().get_additional_checks(meta)) is False


def test_blutopia_requires_ac3_for_each_truehd_track():
    meta = make_meta(mediainfo={"media": {"track": [audio("TrueHD")]}})
    assert asyncio.run(tracker().get_additional_checks(meta)) is False


def test_blutopia_accepts_truehd_with_standalone_ac3():
    meta = make_meta(mediainfo={"media": {"track": [audio("TrueHD"), audio("AC-3")]}})
    assert asyncio.run(tracker().get_additional_checks(meta)) is True

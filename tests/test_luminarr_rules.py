# ruff: noqa: S101

from src.meta import Meta
from src.trackers.UNIT3D.luminarr import Luminarr


def _tracker() -> Luminarr:
    return Luminarr({"DEFAULT": {}, "TRACKERS": {"LUMINARR": {}}})


def _meta(**updates) -> Meta:
    values = {
        "type": "ENCODE",
        "resolution": "1080p",
        "video_encode": "x264",
        "hdr": "",
        "anime": False,
        "genres": ["Drama"],
        "keywords": [],
        "container": "mkv",
        "mediainfo": {"media": {"track": []}},
    }
    values.update(updates)
    return Meta(values)


def test_luminarr_requires_x264_below_1080p_for_all_encodes() -> None:
    tracker = _tracker()

    assert tracker._accepted_encode(_meta(resolution="720p", video_encode="x264"))[0]
    assert not tracker._accepted_encode(_meta(resolution="720p", video_encode="x265"))[0]
    assert not tracker._accepted_encode(_meta(resolution="720p", video_encode="", anime=True, genres=["Animation"]))[0]


def test_luminarr_1080p_live_action_codec_depends_on_hdr() -> None:
    tracker = _tracker()

    assert tracker._accepted_encode(_meta(video_encode="x264"))[0]
    assert not tracker._accepted_encode(_meta(video_encode="x265"))[0]
    assert tracker._accepted_encode(_meta(video_encode="x265", hdr="DV HDR"))[0]
    assert not tracker._accepted_encode(_meta(video_encode="x264", hdr="HDR10"))[0]


def test_luminarr_1080p_animation_and_non_encodes_are_unchanged() -> None:
    tracker = _tracker()

    assert tracker._accepted_encode(_meta(video_encode="x265", anime=True, genres=["Animation"]))[0]
    assert tracker._accepted_encode(_meta(type="REMUX", video_encode="", hdr="HDR10"))[0]


def test_luminarr_reads_encoder_library_evidence() -> None:
    tracker = _tracker()
    meta = _meta(
        video_encode="HEVC",
        hdr="HDR10",
        mediainfo={"media": {"track": [{"@type": "Video", "Encoded_Library_Name": "x265 4.1+1"}]}},
    )

    assert tracker._accepted_encode(meta)[0]

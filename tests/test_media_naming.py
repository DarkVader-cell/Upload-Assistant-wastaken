# ruff: noqa: S101
"""Kitsune filename examples are derived from media data, not old names."""

import copy

import pytest

from src.media_naming import NamingError, release_name, title_token


def info(width=1920, height=1080, codec="AVC", atmos=False, hdr=""):
    return {
        "media": {
            "track": [
                {"@type": "Video", "Width": str(width), "Height": str(height), "Format": codec, "HDR_Format": hdr},
                {
                    "@type": "Audio",
                    "Format": "E-AC-3",
                    "Channels": "6",
                    "ChannelLayout": "L R C LFE Ls Rs",
                    "Format_AdditionalFeatures": "JOC" if atmos else "",
                    "Default": "Yes",
                },
            ]
        }
    }


@pytest.mark.parametrize(
    "title,width,height,codec,atmos,hdr,expected",
    [
        ("Primetime", 1920, 1080, "AVC", False, "", "Primetime.2026.1080p.AMZN.WEB-DL.DDP5.1.H.264-Kitsune.mkv"),
        (
            "Your Mother Your Mother Your Mother",
            3840,
            2160,
            "HEVC",
            True,
            "Dolby Vision",
            "Your.Mother.Your.Mother.Your.Mother.2026.2160p.AMZN.WEB-DL.DDP5.1.Atmos.DV.H.265-Kitsune.mkv",
        ),
        (
            "Your Mother Your Mother Your Mother",
            3840,
            2160,
            "HEVC",
            True,
            "Dolby Vision / SMPTE ST 2094 App 4",
            "Your.Mother.Your.Mother.Your.Mother.2026.2160p.AMZN.WEB-DL.DDP5.1.Atmos.DV.HDR10Plus.H.265-Kitsune.mkv",
        ),
        ("Your Mother Your Mother Your Mother", 1280, 720, "AVC", True, "", "Your.Mother.Your.Mother.Your.Mother.2026.720p.AMZN.WEB-DL.DDP5.1.Atmos.H.264-Kitsune.mkv"),
    ],
)
def test_exact_user_examples(title, width, height, codec, atmos, hdr, expected):
    assert release_name(info(width, height, codec, atmos, hdr), title, 2026, "AMZN") == expected


def test_cropped_movie_is_still_1080p():
    assert ".1080p." in release_name(info(height=804), "Film", 2026, "NF")


def test_hdr10_alone_has_no_dv_label():
    name = release_name(info(codec="HEVC", hdr="SMPTE ST 2086 / HDR10"), "Film", 2026, "AMZN")
    assert ".HDR10.H.265-" in name and ".DV." not in name


def test_no_atmos_invented_from_channel_count():
    assert ".Atmos." not in release_name(info(), "Film", 2026, "AMZN")


def test_multichannel_layout_is_not_guessed():
    document = info()
    document["media"]["track"][1].pop("ChannelLayout")
    with pytest.raises(NamingError):
        release_name(document, "Film", 2026, "AMZN")


def test_multiple_audio_tracks_require_a_unique_default_or_choice():
    document = info()
    document["media"]["track"][1]["Default"] = "No"
    document["media"]["track"].append(copy.deepcopy(document["media"]["track"][1]))
    with pytest.raises(NamingError):
        release_name(document, "Film", 2026, "AMZN")
    assert ".DDP5.1." in release_name(document, "Film", 2026, "AMZN", audio_index=1)


@pytest.mark.parametrize("change", [{"Format": "Unknown"}, {"Width": "unknown"}, {"HDR_Format": "", "transfer_characteristics": "PQ"}])
def test_uncertain_video_metadata_never_produces_a_claim(change):
    document = info()
    document["media"]["track"][0].update(change)
    with pytest.raises(NamingError):
        release_name(document, "Film", 2026, "AMZN")


def test_title_cannot_create_directories_or_hidden_files():
    assert title_token("../A/B: C") == "A.B.C"
    with pytest.raises(NamingError):
        title_token("../..")

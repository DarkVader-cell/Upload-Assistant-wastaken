# ruff: noqa: S101 -- assertions are the test oracle
"""Independent documented-output vectors; no upstream test code is bundled."""

import pytest

from src.media_output import context, format_name, resolution, sanitize
from src.media_template import validate_options


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (1920, 800, 1080),
        (3840, 1600, 2160),
        (1080, 1920, 1080),
        (1280, 720, 720),
        (4096, 2160, 2160),
        (2560, 1080, 1080),
        (720, 576, 576),
        (720, 480, 480),
        (640, 360, 360),
        (1162, 872, 872),
    ],
)
def test_documented_resolution_tiers(width, height, expected):
    assert resolution(width, height) == expected


@pytest.mark.parametrize(
    ("template", "values", "expected"),
    [
        ("{title}.{year?}.{quality?}-{tag?}", {"title": "A Quiet Test", "year": "", "quality": "1080p", "tag": ""}, "A.Quiet.Test.1080p"),
        ("{title} ({year?}) [{quality?}]", {"title": "A Quiet Test", "year": "", "quality": ""}, "A Quiet Test"),
        ("{title}.{edition?}-{tag}", {"title": "A Quiet Test", "edition": "", "tag": "TEAM"}, "A.Quiet.Test-TEAM"),
        ("{title} - {edition?} - {year}", {"title": "A Quiet Test", "edition": "", "year": 2024}, "A Quiet Test - 2024"),
        ("{title}.{video}", {"title": "N.A.S.A. - A Test", "video": "H.264"}, "N.A.S.A.A.Test.H.264"),
        ("{title} {video}", {"title": "N.A.S.A. - A Test", "video": "H.264"}, "N.A.S.A. - A Test H.264"),
    ],
)
def test_optional_separator_and_acronym_rules(template, values, expected):
    assert format_name(template, values) == expected


def media():
    return {
        "media": {
            "track": [
                {"@type": "Video", "Format": "HEVC", "Width": "1920", "Height": "800", "FrameRate": "60000/1001", "TransferCharacteristics": "PQ"},
                {"@type": "Audio", "Format": "AAC", "Language": "en", "ChannelLayout": "L R"},
                {"@type": "Audio", "Format": "E-AC-3", "Language": "fr", "ChannelLayout": "L R C LFE Ls Rs Tfl Tfr", "Format_AdditionalFeatures": "JOC"},
            ]
        }
    }


def test_context_uses_original_audio_and_true_stream_properties():
    values = context(media(), "A $tory", 2024, "AMZN", "TEAM", original_language="fr")
    assert values["title"] == "A Story"
    assert values["quality"] == "1080p"
    assert values["audio_full"] == "DDP5.1.2"
    assert values["atmos"] == "Atmos"
    assert values["video"] == "H.265" and values["hdr"] == "HDR" and values["hfr"] == "HFR"
    assert values["dual"] == "DUAL" and not values["dubbed"]
    template = "{title}.{year}.{quality}.{source}.WEB-DL.{audio_full}.{atmos?}.{video}.{hdr?}-{tag?}"
    assert format_name(template, values) == "A.Story.2024.1080p.AMZN.WEB-DL.DDP5.1.2.Atmos.H.265.HDR-TEAM"


def test_codec_aliases_and_first_matching_group_rule():
    options = validate_options(
        codec_names={"H.265": "HEVC", "DDP": "EAC3", "HDR": "HDR10"},
        tag_rules=[{"when": {"quality": ["1080p", "2160p"], "hdr": "HDR10"}, "tag": "FIRST"}, {"when": {"source": "AMZN"}, "tag": "SECOND"}],
    )
    values = context(media(), "Sample", 2024, "AMZN", "BASE", original_language="fr", options=options)
    assert values["audio_full"] == "EAC3 5.1.2"
    assert values["video"] == "HEVC" and values["hdr"] == "HDR10" and values["tag"] == "FIRST"


def test_language_count_mode_is_explicit_and_no_source_is_respected():
    strict = context(media(), "Sample", 2024, "NF")
    count = context(media(), "Sample", 2024, "NF", options={"dual_multi_mode": "count", "no_source": True})
    assert not strict["dual"] and count["dual"] == "DUAL" and count["source"] == ""


def test_unicode_preserves_nfc_and_ascii_is_transliterated():
    assert sanitize("Cafe\u0301 東京", unicode_filenames=True) == "Café.東京"
    assert sanitize("Cafe\u0301") == "Cafe"
    assert sanitize("[(Example)]") == "[Example]"
    assert sanitize("A/B;C: D?") == "A.&.B.&.C.D"


def test_series_parts_and_absolute_numbers_are_identity_not_guessed():
    values = context(media(), "A Series", 2024, "NF", title_data={"title_type": "series", "season": 2, "episode": 3, "part": 2, "absolute": 17, "episode_name": "The Test"})
    assert values["season"] == "S02" and values["episode"] == "E03.Part.2"
    assert values["season_episode"] == "S02E03.Part.2" and values["absolute"] == "017"
    with pytest.raises(ValueError, match="exact season"):
        context(media(), "A Series", 2024, "NF", title_data={"title_type": "series"})


@pytest.mark.parametrize("template", ["{title.__class__}", "{title!r}", "{title:20000}", "{unknown}", "{title"])
def test_no_format_expressions_or_arbitrary_attributes(template):
    with pytest.raises(ValueError):
        format_name(template, {"title": "Example"})


@pytest.mark.parametrize(
    "options",
    [{"folder_template": "../outside"}, {"tag_rules": [{"when": {"title": "Example"}, "tag": "TEAM"}]}, {"codec_names": {"H.265": "../fake"}}, {"unicode_filenames": "yes"}],
)
def test_options_are_constrained_to_safe_data(options):
    with pytest.raises(ValueError):
        validate_options(**options)

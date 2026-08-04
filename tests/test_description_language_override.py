# ruff: noqa: S101
from src.get_desc import DescriptionBuilder
from src.meta import Meta


def test_manual_audio_language_values_are_normalized_for_description() -> None:
    meta = Meta(manual_audio_languages=["Tamil, English", "Tamil"])

    assert DescriptionBuilder._manual_audio_language_values(meta) == ["Tamil", "English"]


def test_manual_audio_language_values_accept_a_single_string() -> None:
    meta = Meta(manual_audio_languages="Tamil")

    assert DescriptionBuilder._manual_audio_language_values(meta) == ["Tamil"]

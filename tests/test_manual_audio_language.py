from src.languages import LanguagesManager
from src.meta import Meta


def test_manual_audio_languages_accepts_multiple_values_and_commas() -> None:
    meta = Meta(manual_audio_languages=["Tamil, English", "Tamil"])

    assert LanguagesManager._manual_audio_languages(meta) == ["Tamil", "English"]  # noqa: S101

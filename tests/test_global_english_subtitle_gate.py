from src.meta import Meta
from src.trackerstatus import requires_english_subtitles_for_non_english_audio


def test_non_english_audio_requires_english_subtitles_for_regular_trackers() -> None:
    meta = Meta(category="MOVIE", audio_languages=["Tamil"], subtitle_languages=["Tamil"])

    assert requires_english_subtitles_for_non_english_audio(meta, "AITHER") is True


def test_english_subtitle_codes_satisfy_global_gate() -> None:
    meta = Meta(category="TV", audio_languages=["jpn"], subtitle_languages=["en"])

    assert requires_english_subtitles_for_non_english_audio(meta, "BLUTOPIA") is False


def test_english_sdh_subtitles_satisfy_global_gate() -> None:
    meta = Meta(category="TV", audio_languages=["Japanese"], subtitle_languages=["English (SDH)"])

    assert requires_english_subtitles_for_non_english_audio(meta, "AITHER") is False


def test_english_audio_does_not_require_english_subtitles() -> None:
    meta = Meta(category="MOVIE", audio_languages=["English"], subtitle_languages=[])

    assert requires_english_subtitles_for_non_english_audio(meta, "AITHER") is False


def test_desitorrents_is_exempt_from_global_gate() -> None:
    meta = Meta(category="MOVIE", audio_languages=["Tamil"], subtitle_languages=[])

    assert requires_english_subtitles_for_non_english_audio(meta, "DESITORRENTS") is False

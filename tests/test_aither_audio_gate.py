from src.meta import Meta
from src.trackers.UNIT3D.aither import Aither


def _checker() -> Aither:
    return Aither.__new__(Aither)


def test_aither_rejects_duplicate_primary_audio_language() -> None:
    meta = Meta(
        {
            "mediainfo": {
                "media": {
                    "track": [
                        {"@type": "Audio", "Language": "en", "Title": "Surround"},
                        {"@type": "Audio", "Language": "en", "Title": "Stereo"},
                    ]
                }
            }
        }
    )
    assert _checker()._audio_tracks_allowed(meta) is False


def test_aither_allows_commentary_and_compatibility_tracks() -> None:
    meta = Meta(
        {
            "mediainfo": {
                "media": {
                    "track": [
                        {"@type": "Audio", "Language": "en", "Title": "Surround"},
                        {"@type": "Audio", "Language": "en", "Title": "Compatibility"},
                        {"@type": "Audio", "Language": "en", "Title": "Commentary"},
                    ]
                }
            }
        }
    )
    assert _checker()._audio_tracks_allowed(meta) is True


def test_aither_allows_original_language_only() -> None:
    meta = Meta(
        {
            "original_language": "Tamil",
            "mediainfo": {"media": {"track": [{"@type": "Audio", "Language": "tam", "Title": "Main"}]}},
        }
    )
    assert _checker()._audio_tracks_allowed(meta) is True


def test_aither_allows_only_english_japanese_dual_audio() -> None:
    meta = Meta(
        {
            "original_language": "Japanese",
            "mediainfo": {"media": {"track": [{"@type": "Audio", "Language": "eng"}, {"@type": "Audio", "Language": "jpn"}]}},
        }
    )
    assert _checker()._audio_tracks_allowed(meta) is True


def test_aither_rejects_non_original_non_japanese_english_dual_audio() -> None:
    meta = Meta(
        {
            "original_language": "Tamil",
            "mediainfo": {"media": {"track": [{"@type": "Audio", "Language": "tam"}, {"@type": "Audio", "Language": "eng"}]}},
        }
    )
    assert _checker()._audio_tracks_allowed(meta) is False

import asyncio

from src.audio import AudioManager
from src.meta import Meta


def _mediainfo_with_surround_ex() -> dict:
    return {
        "media": {
            "track": [
                {
                    "@type": "Audio",
                    "Format": "E-AC-3",
                    "Format_Commercial": "Dolby Digital Plus",
                    "Format_Settings": "Dolby Surround EX",
                    "Channels": "6",
                    "ChannelLayout": "L R C LFE Ls Rs",
                    "Language": "en",
                }
            ]
        }
    }


def test_surround_ex_is_not_added_to_web_release_audio_name():
    meta = Meta(source="WEB", type="WEBDL", category="TV", original_language="en")

    audio, channels, _ = asyncio.run(AudioManager({}).get_audio_v2(_mediainfo_with_surround_ex(), meta, None))

    assert channels == "5.1"  # noqa: S101
    assert audio == "DD+ 5.1"  # noqa: S101


def test_surround_ex_is_retained_for_non_web_release_audio_name():
    meta = Meta(source="BLURAY", type="DISC", category="MOVIE", original_language="en")

    audio, channels, _ = asyncio.run(AudioManager({}).get_audio_v2(_mediainfo_with_surround_ex(), meta, None))

    assert channels == "5.1"  # noqa: S101
    assert audio == "DD+ EX 5.1"  # noqa: S101

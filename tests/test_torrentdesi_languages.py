from src.trackers.UNIT3D.torrentdesi import INDIAN_LANGUAGES


def test_torrentdesi_indian_language_list_contains_required_aliases() -> None:
    languages = set(INDIAN_LANGUAGES)
    assert {"hindi", "hin", "hi", "bengali", "bangla", "bn", "punjabi", "panjabi", "odia", "oriya"} <= languages

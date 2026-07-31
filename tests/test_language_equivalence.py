from src.trackers.common import Common


def test_indian_language_aliases_are_equivalent() -> None:
    common = Common.__new__(Common)
    lookup = common._build_language_alias_lookup()

    assert common._expand_language_candidates("bn", lookup) >= {"bengali", "bangla", "ben", "bn"}
    assert common._expand_language_candidates("Panjabi", lookup) >= {"punjabi", "panjabi", "pan", "pa"}
    assert common._expand_language_candidates("ori", lookup) >= {"odia", "oriya", "ori", "or"}

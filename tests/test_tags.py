from src.tags import canonicalize_release_group


def test_fried_chicken_please_group_is_canonicalized_before_validation() -> None:
    assert canonicalize_release_group("Fried.Chicken.Please") == "FriedChickenPlease"


def test_unknown_release_group_is_unchanged() -> None:
    assert canonicalize_release_group("OtherGroup") == "OtherGroup"

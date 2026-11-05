# ruff: noqa: S101
"""Selection criteria apply to discovery and previously queued titles."""

from src.catalogue_runner import selection_matches


def test_year_range_and_future_or_unknown_years():
    assert selection_matches({"title": "Fixture", "year": 2024}, {})
    assert not selection_matches({"title": "Fixture", "year": 3000}, {})
    assert not selection_matches({"title": "Fixture", "year": None}, {})
    assert not selection_matches({"title": "Fixture", "year": True}, {})
    assert not selection_matches({"title": "Fixture", "year": 1990}, {"min_release_year": 2020})
    assert not selection_matches({"title": "Fixture", "year": 2025}, {"max_release_year": 2024})


def test_exclusions_are_literal_casefolded_and_empty_titles_fail():
    assert not selection_matches({"title": "Fixture TRAILER", "year": 2024}, {"exclude_title_keywords": ["trailer"]})
    assert selection_matches({"title": "Fixture", "year": 2024}, {"exclude_title_keywords": [".*"]})
    assert not selection_matches({"title": "  ", "year": 2024}, {})

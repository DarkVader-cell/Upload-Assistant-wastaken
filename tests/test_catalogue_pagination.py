# ruff: noqa: S101
"""The live API ignores `after` unless its absolute cursor offset is supplied."""

import base64

import pytest

from src.catalogue_runner import Catalogue, RunnerError, catalogue_offset, discover


def test_numeric_cursor_is_absolute_not_reset_to_zero():
    assert catalogue_offset(None, 120) == 120
    assert catalogue_offset("MTYw", 120) == 160
    assert catalogue_offset("NDA=", 0) == 40
    assert catalogue_offset("80", 0) == 80


@pytest.mark.parametrize("cursor", ["opaque-cursor", "-1", "!!!!", "a" * 100])
def test_unrecognized_cursor_is_never_guessed(cursor):
    with pytest.raises(RunnerError):
        catalogue_offset(cursor)


def test_three_page_discovery_advances_actual_offset():
    offsets = []
    cursors = {}

    class API:
        def request(self, _method, _url, **kwargs):
            offset = kwargs["json"]["variables"]["offset"]
            offsets.append(offset)
            next_cursor = base64.b64encode(str(offset + 40).encode()).decode() if offset < 80 else None
            return {"data": {"popularTitles": {"edges": [], "pageInfo": {"hasNextPage": offset < 80, "endCursor": next_cursor}}}}

    class Store:
        def cursor(self, key):
            return cursors.get(key)

        def page(self, key, _candidates, cursor):
            cursors[key] = cursor

    discover({"services": {"netflix": {"region": "US"}}, "pages_per_service": 3}, Catalogue(API()), Store())
    assert offsets == [0, 40, 80]
    assert list(cursors.values()) == [None]

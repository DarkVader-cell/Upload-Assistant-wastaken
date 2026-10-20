# ruff: noqa: S101
"""Regression tests for combined metadata lookup state."""

from typing import ClassVar

import pytest

from src import metadata_searching
from src.meta import Meta


@pytest.mark.asyncio
async def test_combined_tmdb_lookup_marks_metadata_as_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeTmdb:
        config: ClassVar[dict[str, object]] = {}

        async def tmdb_other_meta(self, **_kwargs):
            return {"title": "Example", "year": 2024}

    async def imdb_info(*_args, **_kwargs):
        return {"title": "Example"}

    monkeypatch.setattr(metadata_searching.imdb_manager, "get_imdb_info_api", imdb_info)
    meta = Meta(category="MOVIE", tmdb_id=123, imdb_id=456)

    await metadata_searching.imdb_tmdb(meta, "Example.2024.mkv", None, FakeTmdb())

    assert meta.title == "Example"
    assert meta._tmdb_metadata_loaded is True
    assert "_tmdb_metadata_loaded" not in meta.to_dict()

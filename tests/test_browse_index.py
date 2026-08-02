# ruff: noqa: S101

from pathlib import Path

from web_ui.browse_index import BrowseIndex


def test_browse_index_searches_without_rescanning_every_query(tmp_path, monkeypatch):
    root = tmp_path / "media"
    release = root / "Movie.2026"
    release.mkdir(parents=True)
    (release / "Movie.2026.1080p.mkv").write_bytes(b"data")
    database = tmp_path / "browse.sqlite3"
    index = BrowseIndex(database, refresh_seconds=900)

    first, indexing = index.search([str(root)], "Movie 2026", "video", 100)
    assert not indexing
    assert {Path(item["path"]).name for item in first} == {"Movie.2026", "Movie.2026.1080p.mkv"}

    def fail_walk(*_args, **_kwargs):
        raise AssertionError("search unexpectedly rescanned the browse root")

    monkeypatch.setattr("web_ui.browse_index.os.walk", fail_walk)
    second, _ = index.search([str(root)], "Movie 2026", "video", 100)
    assert {Path(item["path"]).name for item in second} == {"Movie.2026", "Movie.2026.1080p.mkv"}


def test_browse_index_refreshes_stale_entries(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    (root / "old.mkv").touch()
    index = BrowseIndex(tmp_path / "browse.sqlite3", refresh_seconds=30)
    index.search([str(root)], "old", "video", 100)

    (root / "new.mkv").touch()
    index._refresh([str(root)])
    results, _ = index.search([str(root)], "new", "video", 100)
    assert [item["name"] for item in results] == ["new.mkv"]

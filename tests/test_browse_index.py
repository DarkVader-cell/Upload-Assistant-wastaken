# ruff: noqa: S101

import threading
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


def test_browse_index_batches_large_subtrees_and_respects_result_limit(tmp_path, monkeypatch):
    root = tmp_path / "media"
    root.mkdir()
    for number in range(2005):
        (root / f"Episode.{number:04d}.mkv").touch()

    index = BrowseIndex(tmp_path / "browse.sqlite3", refresh_seconds=900)
    index._initialize()
    index._sync_subtree(str(root.resolve()), root)

    with index._connect() as connection:
        count = connection.execute("SELECT COUNT(*) FROM browse_entries").fetchone()[0]
    assert count == 2005

    monkeypatch.setattr(index, "_watcher_available", lambda: False)
    results, indexing = index.search([str(root)], "Episode", "video", 5)
    assert not indexing
    assert len(results) == 5


def test_browse_index_close_stops_the_active_watcher(tmp_path, monkeypatch):
    index = BrowseIndex(tmp_path / "browse.sqlite3")
    started = threading.Event()

    def watch(_roots):
        started.set()
        index._watch_stop.wait()

    monkeypatch.setattr(index, "_watcher_available", lambda: True)
    monkeypatch.setattr(index, "_watch_filesystem", watch)
    index._start_watcher([str(tmp_path)])
    assert started.wait(timeout=1)
    index.close()
    assert index._watch_thread is None

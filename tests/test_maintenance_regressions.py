"""Regression coverage for the upstream maintenance integration seams."""

import asyncio
import sqlite3

import httpx
import pytest

from src.meta import Meta
from src.runtime.context import ExecutionContext
from src.runtime.history import ReleaseHistoryStore
from src.runtime.http import HttpClientPool
from src.trackers.czteam import CZTeam
from src.trackers.dirtybytes import DirtyBytes
from src.trackers.UNIT3D.hawkeuno import HawkeUno
from web_ui.browse_index import BrowseIndex


def test_http_pool_preserves_case_sensitive_header_values():
    async def run():
        async with HttpClientPool() as pool:
            first = await pool.client("tracker", headers={"Authorization": "Bearer SecretA"})
            equivalent = await pool.client("tracker", headers={"authorization": "Bearer SecretA"})
            different = await pool.client("tracker", headers={"Authorization": "Bearer secreta"})
            assert first is equivalent
            assert different is not first
            assert different.headers["Authorization"] == "Bearer secreta"

    asyncio.run(run())


@pytest.mark.parametrize("tracker_class", [CZTeam, DirtyBytes])
def test_new_api_tracker_searches_reuse_context_owned_client(tmp_path, monkeypatch, tracker_class):
    original_client = httpx.AsyncClient
    clients = []
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=[])

    def create_client(**kwargs):
        client = original_client(transport=httpx.MockTransport(respond), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(httpx, "AsyncClient", create_client)
    tracker = tracker_class({"TRACKERS": {tracker_class.tracker: {}}})

    async def run():
        async with ExecutionContext.create(tmp_path, {}) as context:
            meta = Meta(title="Example", basename_no_ext="Example")
            assert await tracker.search_existing(meta) == []
            assert await tracker.search_existing(meta) == []
            assert len(clients) == 1
            assert not clients[0].is_closed
            assert context.http._clients
        assert clients[0].is_closed
        assert len(requests) == 2

    asyncio.run(run())


def test_hawkeuno_type_lookup_retains_unit3d_keyword_contract():
    tracker = HawkeUno({"DEFAULT": {}, "TRACKERS": {"HAWKEUNO": {}}})
    assert asyncio.run(tracker.get_type_id(Meta(), type="WEBDL")) == {"type_id": "3"}


def test_czteam_manual_name_is_verbatim():
    tracker = CZTeam({"TRACKERS": {"CZTEAM": {}}})
    meta = Meta(manual_name="Exact custom release name", scene_name="Scene.Name", basename_no_ext="Filename")
    assert asyncio.run(tracker.get_name(meta)) == "Exact custom release name"


def test_history_operations_close_connections(tmp_path, monkeypatch):
    history = ReleaseHistoryStore(tmp_path)
    original_connect = history._connect
    connections = []

    def connect():
        connection = original_connect()
        connections.append(connection)
        return connection

    monkeypatch.setattr(history, "_connect", connect)
    history.record_release(Meta(uuid="release", name="Example"))
    assert len(history.search()) == 1
    assert history.stats()["entries"] == 1
    assert len(connections) == 3
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")


def test_browse_connection_is_closed_on_success_and_failure(tmp_path):
    index = BrowseIndex(tmp_path / "browse.sqlite")
    with index._connect() as connection:
        connection.execute("CREATE TABLE example (value TEXT)")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
    with pytest.raises(RuntimeError), index._connect() as failed:
        failed.execute("INSERT INTO example VALUES ('rolled back')")
        raise RuntimeError("rollback")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        failed.execute("SELECT 1")
    with index._connect() as check:
        assert check.execute("SELECT COUNT(*) FROM example").fetchone()[0] == 0


def test_browse_delete_treats_paths_literally_and_case_sensitively(tmp_path):
    index = BrowseIndex(tmp_path / "browse.sqlite")
    root = tmp_path / "media"
    target = root / "Release_[1]%"
    neighbors = [root / "ReleaseX[1]other", root / "release_[1]%", root / "Release_[1]%extra"]
    # Exercise SQLite's literal-path contract without requiring a filesystem
    # that can create two names differing only in case (Windows cannot).
    index._initialize()
    with index._connect() as connection:
        for folder in [target, *neighbors]:
            index._upsert_entry(connection, str(root), folder, "folder")
            index._upsert_entry(connection, str(root), folder / "movie.mkv", "file")
        index._delete_path(connection, target)
        remaining = {row[0] for row in connection.execute("SELECT path FROM browse_entries")}
    assert str(target) not in remaining
    assert str(target / "movie.mkv") not in remaining
    for neighbor in neighbors:
        assert str(neighbor) in remaining
        assert str(neighbor / "movie.mkv") in remaining


def test_browse_directory_sync_removes_missing_descendants_only(tmp_path):
    index = BrowseIndex(tmp_path / "browse.sqlite")
    root = tmp_path / "media"
    changed = root / "changed"
    removed = changed / "removed"
    removed.mkdir(parents=True)
    (removed / "stale.mkv").touch()
    sibling = root / "unchanged"
    sibling.mkdir()
    (sibling / "kept.mkv").touch()
    index._refresh([str(root)])
    (removed / "stale.mkv").unlink()
    removed.rmdir()
    index._sync_directory(str(root), changed)
    with index._connect() as connection:
        paths = {row[0] for row in connection.execute("SELECT path FROM browse_entries")}
    assert str(removed) not in paths
    assert str(removed / "stale.mkv") not in paths
    assert str(sibling / "kept.mkv") in paths

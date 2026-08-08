# ruff: noqa: S101

from src.meta import Meta
from src.runtime.history import ReleaseHistoryStore
from web_ui.services.config_references import torrent_client_reference_updates


def test_release_history_upserts_qui_job_with_prepared_metadata(tmp_path, monkeypatch) -> None:
    store = ReleaseHistoryStore(tmp_path, {"DEFAULT": {"release_history_db": "history.sqlite3"}})
    store.record_job({"id": "qui-1", "source_path": "/media/Movie", "status": "queued", "created_at": "2026-08-08T00:00:00+00:00"})
    monkeypatch.setenv("UA_DETACHED_JOB_ID", "qui-1")
    meta = Meta(
        path="/media/Movie",
        name="Movie.2026.1080p.BluRay",
        category="MOVIE",
        type="ENCODE",
        resolution="1080p",
        trackers=["AITHER", "HDBITS"],
        tracker_status={"AITHER": {"upload_success": True}, "HDBITS": {"upload_success": False}},
        imdb_id=12345,
    )

    assert store.record_release(meta) == "qui-1"
    results = store.search("AITHER", "completed")

    assert len(results) == 1
    assert results[0]["release_name"] == "Movie.2026.1080p.BluRay"
    assert results[0]["successful_trackers"] == ["AITHER"]
    assert results[0]["failed_trackers"] == ["HDBITS"]
    assert results[0]["external_ids"] == {"imdb_id": "12345"}
    assert store.stats() == {"entries": 1, "completed": 1, "failed": 0}


def test_release_history_filters_status_without_loading_unrelated_rows(tmp_path) -> None:
    store = ReleaseHistoryStore(tmp_path, {"DEFAULT": {"release_history_db": "history.sqlite3"}})
    store.record_job({"id": "one", "source_path": "/media/One", "status": "completed"})
    store.record_job({"id": "two", "source_path": "/media/Two", "status": "failed"})

    assert [item["id"] for item in store.search(status="failed")] == ["two"]
    assert store.stats() == {"entries": 2, "completed": 1, "failed": 1}


def test_torrent_client_reference_cleanup_selects_safe_fallback() -> None:
    config = {
        "DEFAULT": {
            "default_torrent_client": "primary",
            "injecting_client_list": ["primary", "seedbox"],
            "searching_client_list": ["primary"],
        },
        "TORRENT_CLIENTS": {"primary": {"torrent_client": "qbit"}, "seedbox": {"torrent_client": "qbit"}},
    }

    assert torrent_client_reference_updates(config, "primary") == [
        (["DEFAULT", "default_torrent_client"], "seedbox"),
        (["DEFAULT", "injecting_client_list"], ["seedbox"]),
        (["DEFAULT", "searching_client_list"], None),
    ]


def test_torrent_client_reference_cleanup_does_not_confuse_client_type() -> None:
    config = {"DEFAULT": {"default_torrent_client": "primary"}, "TORRENT_CLIENTS": {"primary": {"torrent_client": "qbit"}}}

    assert torrent_client_reference_updates(config, "qbit") == []

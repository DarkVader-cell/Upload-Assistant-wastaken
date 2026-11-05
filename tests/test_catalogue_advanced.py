# ruff: noqa: S101
"""Offline contracts for episode identity, safe slots, migration, and quotas."""

import json
import sqlite3
import time

import pytest

from src.catalogue_metadata import episodes_from_listing, planned_profile, verify_identity
from src.catalogue_runner import RunnerError, utc_day
from src.catalogue_slots import eligible
from src.catalogue_store import Store, job_key


def candidate():
    return {"imdb": "tt1234567", "title": "Fixture", "year": 2024, "service": "netflix", "region": "US", "item": "123"}


def test_provider_identity_never_uses_title_only():
    value = candidate()
    assert verify_identity(value, {"item": {"id": "123", "title": "FIXTURE", "year": None}})
    assert not verify_identity(value, {"item": {"id": "other", "title": "Fixture"}})
    assert not verify_identity(value, {"item": {"id": "123", "title": "Fixture", "year": 1999}})
    assert not verify_identity(value, {"item": {"id": "123", "title": "Fixture", "imdb_id": "tt9999999"}})
    assert verify_identity(value, {"item": {"id": "other", "title": "Alternate name", "imdb_id": "tt1234567"}})


def listing():
    return {
        "item": {"id": "123", "title": "Fixture", "year": 2024},
        "seasons": [
            {"id": "season1", "number": 1, "episodes": [{"id": "e1", "episode": 1}, {"id": "e2", "episode": 2}, {"id": "special", "episode": 2.5}]},
            {"id": "season2", "number": 2, "episodes": [{"id": "e3", "episode": 1}]},
        ],
    }


def test_episodes_are_bounded_newest_season_first_and_do_not_starve_old_ones():
    value = {**candidate(), "media_type": "series"}
    first = episodes_from_listing(value, listing(), 1)
    assert first[0]["season"] == 2 and first[0]["job_key"] == "tt1234567:S02E01"
    later = episodes_from_listing(value, listing(), 2, excluded={first[0]["job_key"]})
    assert [entry["job_key"] for entry in later] == ["tt1234567:S01E01", "tt1234567:S01E02"]
    ambiguous = listing()
    ambiguous["seasons"][0]["episodes"].append({"id": "duplicate", "episode": 1})
    for bound in (1, 20):
        with pytest.raises(RunnerError):
            episodes_from_listing(value, ambiguous, bound)


def test_planned_profile_is_from_complete_cardinal_selection():
    item = {"plan": {"ok": True, "resolution": "1080p", "codec": "HEVC", "container": "mkv", "hdr": ["HDR10"], "audio_languages": ["EN"], "subtitle_languages": ["EN"]}}
    value = planned_profile(item, candidate())
    assert value["codec"] == "H265" and value["provider"] == "NF"
    with pytest.raises(RunnerError):
        planned_profile({"plan": {**item["plan"], "audio_languages": ["--login"]}}, candidate())
    for bad in [{}, {"plan": {"ok": False}}, {"plan": {"ok": True, "resolution": "1080p", "codec": "unknown", "hdr": []}}]:
        with pytest.raises(RunnerError):
            planned_profile(bad, candidate())


def test_slot_eligibility_never_promotes_unknown_review_or_trumps():
    trackers = ["HDB", "ATH"]
    good = {"HDB": {"state": "absent"}, "ATH": {"state": "unknown"}}
    assert not eligible(good, "absent_all", trackers)
    assert eligible(good, "missing_any", trackers)
    for flags in [{}, {"requires_evidence": True, "trump": False}, {"requires_evidence": False, "trump": True}]:
        assert not eligible({"HDB": {"state": "allow", **flags}, "ATH": {"state": "block"}}, "missing_or_free_slot", trackers)
    assert eligible({"HDB": {"state": "allow", "requires_evidence": False, "trump": False}, "ATH": {"state": "unknown"}}, "missing_or_free_slot", trackers)
    assert not eligible({"HDB": {"state": "absent"}}, "missing_any", trackers)
    assert not eligible({"PTP": {"state": "not_applicable"}}, "missing_any", ["PTP"])


def test_movie_and_episode_keys_deduplicate_across_services():
    value = candidate()
    assert job_key(value) == "tt1234567"
    episode = {**value, "media_type": "episode", "season": 1, "episode": 2}
    assert job_key(episode) == job_key({**episode, "service": "amazon"}) == "tt1234567:S01E02"
    assert job_key({**value, "media_type": "series"}) == "series:tt1234567"
    with pytest.raises(ValueError):
        job_key({**episode, "job_key": "tt1234567:S01E99"})


def test_v1_migration_retains_backup_reservations_and_history(tmp_path):
    path = tmp_path / "legacy.db"
    db = sqlite3.connect(path)
    db.execute("""CREATE TABLE jobs(imdb TEXT PRIMARY KEY,candidate TEXT,status TEXT,discovered REAL,checked REAL,evidence TEXT,started_day TEXT,service TEXT,reason TEXT)""")
    value = candidate()
    db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)", (value["imdb"], json.dumps(value), "failed", time.time(), None, None, utc_day(), "netflix", "test"))
    db.commit()
    db.close()
    store = Store(path)
    try:
        assert store.db.execute("SELECT count(*) FROM jobs_v1_backup").fetchone()[0] == 1
        assert store.db.execute("SELECT count(*) FROM attempts").fetchone()[0] == 1
        assert not store.reserve(value["imdb"], "netflix", 1, 1)
        with pytest.raises(ValueError):
            store.requeue(value["imdb"])
        store.requeue(value["imdb"], verified=True)
        assert not store.reserve(value["imdb"], "netflix", 1, 1)
        assert store.db.execute("SELECT count(*) FROM attempts").fetchone()[0] == 1
    finally:
        store.db.close()


def test_episode_reservations_count_but_series_expansion_does_not(tmp_path):
    store = Store(tmp_path / "queue.db")
    try:
        parent = {**candidate(), "media_type": "series"}
        first = {**candidate(), "media_type": "episode", "season": 1, "episode": 1}
        second = {**candidate(), "media_type": "episode", "season": 1, "episode": 2}
        store.page("page", [parent, first, second], None)
        assert not store.reserve(job_key(parent), "netflix", 1, 1)
        assert store.reserve(job_key(first), "netflix", 1, 1)
        assert not store.reserve(job_key(second), "netflix", 1, 1)
        store.update(job_key(first), "failed")
        store.requeue(job_key(first), verified=True)
        assert not store.reserve(job_key(first), "netflix", 1, 1)
        assert len(store.episode_keys(candidate()["imdb"])) == 2
    finally:
        store.db.close()


def test_unknown_backoff_is_not_reset_by_catalogue_refresh(tmp_path):
    store = Store(tmp_path / "queue.db")
    try:
        value = candidate()
        store.page("page", [value], None)
        store.update(value["imdb"], "unknown")
        before = store.db.execute("SELECT next_check,error_count FROM jobs").fetchone()
        store.page("page", [value], None)
        after = store.db.execute("SELECT next_check,error_count FROM jobs").fetchone()
        assert tuple(before) == tuple(after) and before[0] > time.time()
    finally:
        store.db.close()

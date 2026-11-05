# ruff: noqa: S101
"""Missing-title finder routing and positive-hit cache must remain fail closed."""

from src.catalogue_runner import process
from src.catalogue_store import Store

CANDIDATE = {"imdb": "tt1234567", "title": "Example", "year": 2020, "service": "amazon", "region": "GB", "item": "B000000001", "origin_countries": [], "media_type": "movie"}


def test_prime_requirement_cannot_be_bypassed_by_basic_movie_mode(monkeypatch):
    from src import catalogue_workflow

    calls = []
    monkeypatch.setattr(catalogue_workflow, "process_advanced", lambda *args, **kwargs: calls.append((args, kwargs)))
    settings = {
        "require_prime_inclusion": True,
        "services": {"amazon": {"region": "GB"}},
        "media_types": ["movie"],
        "video_mode": "saved",
        "eligibility": "absent_all",
        "verify_cardinal": False,
    }
    process(settings, object(), object(), False)
    assert len(calls) == 1


def test_rediscovery_retains_only_fresh_exact_tracker_hit(tmp_path):
    store = Store(tmp_path / "queue.sqlite3")
    store.add(CANDIDATE)
    store.update("tt1234567", "blocked", "Exact title already exists on HDB; stopped remaining tracker/provider requests", {"inventory": {"HDB": "present"}})
    before = store.db.execute("SELECT checked FROM jobs").fetchone()[0]
    store.add(CANDIDATE)
    row = store.db.execute("SELECT status,checked FROM jobs").fetchone()
    assert row["status"] == "blocked" and row["checked"] == before
    store.invalidate_unstarted()
    store.add(CANDIDATE)
    assert store.db.execute("SELECT status FROM jobs").fetchone()[0] == "pending"
    store.db.close()


def test_expired_hit_and_changed_scope_are_rechecked(tmp_path):
    store = Store(tmp_path / "queue.sqlite3")
    store.add(CANDIDATE)
    store.update("tt1234567", "blocked", "Exact title already exists on HDB", evidence={"inventory": {"HDB": "present"}})
    store.db.execute("UPDATE jobs SET checked=checked-21601")
    store.add(CANDIDATE)
    assert store.db.execute("SELECT status FROM jobs").fetchone()[0] == "pending"
    store.update("tt1234567", "blocked", "Exact title already exists on HDB", evidence={"inventory": {"HDB": "present"}})
    store.add({**CANDIDATE, "region": "US"})
    assert store.db.execute("SELECT status FROM jobs").fetchone()[0] == "pending"
    store.db.close()


def test_absence_and_slot_denials_are_never_positive_hit_cache(tmp_path):
    store = Store(tmp_path / "queue.sqlite3")
    store.add(CANDIDATE)
    for evidence in ({"inventory": {"HDB": "absent"}}, {"trackers": {"HDB": {"state": "deny"}}}, {"inventory": {"HDB": "unknown"}}):
        store.update("tt1234567", "blocked", evidence=evidence)
        store.add(CANDIDATE)
        assert store.db.execute("SELECT status FROM jobs").fetchone()[0] == "pending"
    store.db.close()

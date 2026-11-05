# ruff: noqa: S101, ARG002, ARG005 -- test doubles preserve the production calling convention
"""Offline orchestration: no provider/tracker requests or real downloads."""

import copy
import json

import pytest

from src.catalogue_runner import RunnerError, cardinal_command
from src.catalogue_store import Store
from src.catalogue_workflow import process_advanced

PROFILE = {"codec": "H264", "resolution": "1080p", "hdr": [], "hybrid": False, "container": "mkv", "provider": "NF", "audio_languages": ["EN"], "subtitle_languages": []}
CANDIDATE = {
    "imdb": "tt1234567",
    "title": "Offline fixture",
    "year": 2024,
    "service": "netflix",
    "region": "US",
    "item": "12345",
    "origin_countries": [],
    "media_type": "movie",
}


@pytest.fixture
def settings(tmp_path):
    return {
        "services": {"netflix": {"region": "US", "daily_limit": 2}},
        "trackers": ["HDB"],
        "media_types": ["movie", "tv"],
        "eligibility": "missing_or_free_slot",
        "daily_limit": 2,
        "max_checks_per_run": 20,
        "max_downloads_per_run": 2,
        "max_candidate_age_hours": 24,
        "min_free_gib": 0,
        "disk_path": str(tmp_path),
        "timeout_seconds": 10,
        "cardinal_binary": ["never-executed-fixture"],
        "max_episodes_per_title": 1,
    }


class Metadata:
    def __init__(self):
        self.checked = []
        self.episodes = 3

    def item_profile(self, candidate):
        self.checked.append(candidate)
        return copy.deepcopy(PROFILE)

    def list(self, candidate):
        return {
            "requested": candidate["item"],
            "item": {"id": candidate["item"], "title": candidate["title"], "year": 2024},
            "seasons": [{"id": "season-one", "number": 1, "episodes": [{"id": str(i), "episode": i} for i in range(1, self.episodes + 1)]}],
        }


class Slots:
    def __init__(self, state="absent", **flags):
        self.state, self.flags = state, flags
        self.calls = 0

    def check(self, candidate, profile):
        self.calls += 1
        return {"HDB": {"state": self.state, "reason": "Offline fixture only", "requires_evidence": False, "trump": False, **self.flags}}


def add(store, candidate):
    with store.db:
        store.add(candidate)


def test_verified_movie_snapshot_and_fresh_recheck(settings, tmp_path):
    store, metadata, slots, commands = Store(tmp_path / "queue.db"), Metadata(), Slots(), []
    add(store, CANDIDATE)
    process_advanced(settings, store, False, metadata, slots)
    assert store.db.execute("SELECT status FROM jobs").fetchone()[0] == "ready"
    assert store.usage()[0] == 0
    process_advanced(settings, store, True, metadata, slots, lambda command, timeout: commands.append(command) or "succeeded")
    assert slots.calls == 2
    assert len(commands) == 1 and "1080p@h264@sdr" in commands[0] and "--hybrid=false" in commands[0]
    assert commands[0][commands[0].index("--outputformat") + 1] == "mkv"
    assert "--nosubs" in commands[0]
    assert store.usage()[0] == 1
    process_advanced(settings, store, True, metadata, slots, lambda *args: pytest.fail("Completed job replayed"))
    store.db.close()


@pytest.mark.parametrize(
    "state,flags,expected",
    [("unknown", {}, "unknown"), ("review", {}, "review"), ("block", {}, "blocked"), ("allow", {"requires_evidence": True}, "blocked"), ("allow", {"trump": True}, "blocked")],
)
def test_uncertain_slots_never_download(settings, tmp_path, state, flags, expected):
    store = Store(tmp_path / "queue.db")
    add(store, CANDIDATE)
    process_advanced(settings, store, True, Metadata(), Slots(state, **flags), lambda *args: pytest.fail("Unverified job downloaded"))
    assert store.db.execute("SELECT status FROM jobs").fetchone()[0] == expected
    assert store.usage()[0] == 0
    store.db.close()


def test_absence_mode_rejects_known_existing_movie_before_provider_requests(settings, tmp_path):
    class PresentInventory:
        def check_until_hit(self, _imdb):
            return {"HDB": "present"}

    settings["eligibility"] = "absent_all"
    store, metadata = Store(tmp_path / "queue.db"), Metadata()
    add(store, CANDIDATE)
    process_advanced(settings, store, False, metadata, Slots(), inventory=PresentInventory())
    assert not metadata.checked
    assert store.db.execute("SELECT status FROM jobs").fetchone()[0] == "blocked"
    store.db.close()


def test_tv_expansion_refresh_dedup_and_episode_quotas(settings, tmp_path):
    store, metadata, commands = Store(tmp_path / "queue.db"), Metadata(), []
    parent = {**CANDIDATE, "media_type": "series"}
    add(store, parent)
    process_advanced(settings, store, False, metadata, Slots())
    assert dict(store.db.execute("SELECT job_key,status FROM jobs")) == {"series:tt1234567": "expanded", "tt1234567:S01E01": "ready"}
    assert store.usage()[0] == 0
    process_advanced(settings, store, True, metadata, Slots(), lambda command, timeout: commands.append(command) or "succeeded")
    assert "--episode" in commands[0] and commands[0][commands[0].index("--episode") + 1] == "1"
    assert commands[0][commands[0].index("--season") + 1] == "season-one"
    # A fresh catalogue visit advances expansion instead of replaying episode 1.
    add(store, parent)
    process_advanced(settings, store, True, metadata, Slots(), lambda command, timeout: commands.append(command) or "succeeded")
    assert len(commands) == 2 and store.usage()[0] == 2
    assert store.db.execute("SELECT count(*) FROM jobs WHERE status='succeeded'").fetchone()[0] == 2
    process_advanced(settings, store, True, metadata, Slots(), lambda *args: pytest.fail("Daily quota exceeded"))
    store.db.close()


def test_tv_only_never_executes_movie_queue(settings, tmp_path):
    settings["media_types"] = ["tv"]
    store, metadata = Store(tmp_path / "queue.db"), Metadata()
    add(store, CANDIDATE)
    process_advanced(settings, store, True, metadata, Slots(), lambda *args: pytest.fail("Disabled movie category executed"))
    assert metadata.checked == []
    store.db.close()


def test_scoped_queue_and_metadata_failure(settings, tmp_path):
    class BadMetadata(Metadata):
        def item_profile(self, candidate):
            raise RunnerError("Identity mismatch")

    store = Store(tmp_path / "queue.db")
    add(store, CANDIDATE)
    process_advanced(settings, store, True, BadMetadata(), Slots(), lambda *args: pytest.fail("Mismatched identity downloaded"))
    assert store.db.execute("SELECT status FROM jobs").fetchone()[0] == "unknown"
    assert store.usage()[0] == 0
    settings["origin_countries"] = ["IN"]
    process_advanced(settings, store, True, Metadata(), Slots(), lambda *args: pytest.fail("Wrong-country queued item downloaded"))
    store.db.close()


def test_unsafe_cardinal_selectors_rejected(settings):
    for candidate in ({**CANDIDATE, "item": "--login"}, {**CANDIDATE, "media_type": "episode", "season_id": "--login", "season": 1, "episode": 1}):
        with pytest.raises(RunnerError):
            cardinal_command(settings, candidate, PROFILE)


def test_rule_invalidation_preserves_ledger_and_terminal_jobs(tmp_path):
    store = Store(tmp_path / "queue.db")
    add(store, CANDIDATE)
    store.update(CANDIDATE["imdb"], "ready", "Fixture")
    assert store.reserve(CANDIDATE["imdb"], "netflix", 2, 2)
    store.update(CANDIDATE["imdb"], "failed", "Offline synthetic failure")
    store.invalidate_unstarted()
    assert store.db.execute("SELECT status FROM jobs").fetchone()[0] == "failed"
    assert store.usage()[0] == 1
    store.requeue(CANDIDATE["imdb"], verified=True)
    assert store.usage()[0] == 1
    assert json.loads(store.db.execute("SELECT candidate FROM jobs").fetchone()[0])["imdb"] == CANDIDATE["imdb"]
    store.db.close()


def test_repeated_provider_failures_defer_rest_without_requests(settings, tmp_path):
    class BrokenMetadata(Metadata):
        def item_profile(self, candidate):
            self.checked.append(candidate)
            raise RunnerError("Cardinal listing failed")

    store, metadata = Store(tmp_path / "queue.db"), BrokenMetadata()
    for index in range(5):
        add(store, {**CANDIDATE, "imdb": f"tt{8000000 + index}"})
    process_advanced(settings, store, False, metadata, Slots())
    assert len(metadata.checked) == 2
    assert store.db.execute("SELECT count(*) FROM jobs WHERE status='pending'").fetchone()[0] == 3
    store.db.close()


def test_changed_year_filter_stops_old_queued_jobs_before_metadata(settings, tmp_path):
    settings["min_release_year"] = 2025
    store, metadata = Store(tmp_path / "queue.db"), Metadata()
    add(store, CANDIDATE)
    process_advanced(settings, store, False, metadata, Slots())
    assert not metadata.checked
    assert store.db.execute("SELECT status FROM jobs").fetchone()[0] == "pending"  # Outside this selection, retained for other filters.
    store.db.close()


def test_check_budget_is_balanced_across_configured_services(settings, tmp_path):
    settings["services"]["amazon"] = {"region": "GB", "daily_limit": 2}
    settings["max_checks_per_run"] = 2
    store, metadata = Store(tmp_path / "queue.db"), Metadata()
    for index in range(20):
        add(store, {**CANDIDATE, "imdb": f"tt{8000000 + index}"})
    add(store, {**CANDIDATE, "imdb": "tt9000001", "service": "amazon", "region": "GB"})
    process_advanced(settings, store, False, metadata, Slots())
    assert {value["service"] for value in metadata.checked} == {"netflix", "amazon"}
    store.db.close()


def test_provider_unavailable_is_not_a_vacant_slot(settings, tmp_path):
    from src.catalogue_metadata import PlaybackUnavailableError

    class NoPlayback(Metadata):
        def item_profile(self, candidate):
            raise PlaybackUnavailableError("Provider returned no playable full-title offer")

    store = Store(tmp_path / "queue.db")
    add(store, CANDIDATE)
    process_advanced(settings, store, True, NoPlayback(), Slots(), lambda *_args: pytest.fail("Unavailable title downloaded"))
    assert store.db.execute("SELECT status FROM jobs").fetchone()[0] == "unavailable"
    assert store.usage()[0] == 0
    store.db.close()


def test_rare_budget_is_not_consumed_by_old_popular_queue(settings, tmp_path):
    settings.update(max_checks_per_run=1, max_release_year=2015, min_imdb_votes=10, max_imdb_votes=5000, min_runtime_minutes=30)
    store, metadata = Store(tmp_path / "queue.db"), Metadata()
    for index in range(20):
        add(store, {**CANDIDATE, "imdb": f"tt{8000000 + index}"})
    add(store, {**CANDIDATE, "imdb": "tt9000001", "year": 1985, "imdb_votes": 200, "runtime_minutes": 90, "is_released": True})
    process_advanced(settings, store, False, metadata, Slots())
    assert [item["imdb"] for item in metadata.checked] == ["tt9000001"]
    store.db.close()

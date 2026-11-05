# ruff: noqa: S101, ARG002
"""Original language is identity metadata, never country or selected dubbing."""

import json

import pytest
from test_catalogue_workflow import CANDIDATE, Metadata, Slots

from src.catalogue_runner import RunnerError, Trackers, discover, load_settings, selection_matches, verify_original_language
from src.catalogue_store import Store
from src.catalogue_workflow import process_advanced, rows_for


@pytest.fixture
def settings(tmp_path):
    return {
        "services": {"netflix": {"region": "US"}},
        "trackers": ["HDB"],
        "media_types": ["movie"],
        "eligibility": "absent_all",
        "daily_limit": 1,
        "max_checks_per_run": 10,
        "max_downloads_per_run": 1,
        "max_candidate_age_hours": 24,
        "min_free_gib": 0,
        "disk_path": str(tmp_path),
        "timeout_seconds": 5,
        "cardinal_binary": "never-executed-fixture",
        "original_languages": ["ta"],
    }


class Inventory:
    def __init__(self, language="ta", hit=False):
        self.language = language
        self.hit = hit
        self.language_calls = 0

    def check_until_hit(self, imdb):
        return {"HDB": "present" if self.hit else "absent"}

    def original_language(self, imdb, media_type):
        self.language_calls += 1
        if self.language is None:
            raise RunnerError("Original language unavailable; no provider request permitted")
        return self.language


@pytest.mark.parametrize("language,expected", [("ta", "ready"), ("hi", "filtered"), (None, "unknown")])
def test_language_gate_before_provider_and_download(tmp_path, settings, language, expected):
    store = Store(tmp_path / "state")
    store.add(dict(CANDIDATE))
    store.db.commit()
    metadata = Metadata()
    process_advanced(settings, store, False, metadata=metadata, slots=Slots(), inventory=Inventory(language))
    assert store.db.execute("SELECT status FROM jobs").fetchone()[0] == expected
    assert bool(metadata.checked) == (expected == "ready")
    assert store.db.execute("SELECT count(*) FROM attempts").fetchone()[0] == 0
    store.db.close()


def test_first_tracker_hit_still_stops_language_and_provider_calls(tmp_path, settings):
    store = Store(tmp_path / "state")
    store.add(dict(CANDIDATE))
    store.db.commit()
    metadata = Metadata()
    inventory = Inventory(hit=True)
    process_advanced(settings, store, False, metadata=metadata, slots=Slots(), inventory=inventory)
    assert not metadata.checked and inventory.language_calls == 0
    assert store.db.execute("SELECT status FROM jobs").fetchone()[0] == "blocked"
    store.db.close()


def test_verified_language_survives_rediscovery_and_filters_before_limit(tmp_path, settings):
    store = Store(tmp_path / "state")
    candidate = dict(CANDIDATE)
    store.add(candidate)
    store.db.commit()
    assert not verify_original_language(settings, Inventory("hi"), store, candidate)
    store.add(dict(CANDIDATE))
    store.db.commit()
    assert json.loads(store.db.execute("SELECT candidate FROM jobs").fetchone()[0])["original_language"] == "hi"
    assert rows_for(settings, store, False, False, 1) == []
    store.db.close()


def test_unknown_language_never_inferred_from_country(settings):
    assert selection_matches({**CANDIDATE, "origin_countries": ["IN"]}, settings)
    assert not selection_matches({**CANDIDATE, "original_language": "hi"}, settings)
    assert selection_matches({**CANDIDATE, "original_language": "ta"}, settings)


def test_mapping_and_language_share_exact_imdb_response():
    class API:
        calls = 0

        def request(self, *args, **kwargs):
            self.calls += 1
            return {"movie_results": [{"id": 42, "original_language": "ta"}]}

    api = API()
    tracker = Trackers(api, {"DEFAULT": {"tmdb_api": "fixture"}}, [])
    assert tracker.tmdb_movie("tt1234567") == 42
    assert tracker.original_language("tt1234567") == "ta" and api.calls == 1


@pytest.mark.parametrize("rows", [[], [{"id": 42}], [{"id": 42, "original_language": "ta"}, {"id": 43, "original_language": "hi"}]])
def test_unknown_or_ambiguous_language_is_not_accepted(rows):
    class API:
        def request(self, *args, **kwargs):
            return {"movie_results": rows}

    with pytest.raises(RunnerError):
        Trackers(API(), {"DEFAULT": {"tmdb_api": "fixture"}}, []).original_language("tt1234567")


@pytest.mark.parametrize("languages", ["ta", ["Tamil"], ["TA"], ["ta", "ta"], [None], ["ta", "te", "hi"]])
def test_language_settings_validation(tmp_path, languages):
    ua_file = tmp_path / "ua.py"
    ua_file.write_text('config = {"DEFAULT": {}, "TRACKERS": {"HDBITS": {"username": "fixture", "passkey": "fixture"}}}')
    path = tmp_path / "runner.json"
    path.write_text(json.dumps({"ua_config": str(ua_file), "services": {"netflix": {}}, "trackers": ["HDB"], "original_languages": languages}))
    if languages == ["ta", "te", "hi"]:
        assert load_settings(path)[0]["original_languages"] == languages
    else:
        with pytest.raises(RunnerError):
            load_settings(path)


def test_series_language_gate_runs_before_episode_manifest(tmp_path, settings):
    class ForbiddenMetadata:
        def list(self, *args):
            raise AssertionError("No listing for a different original language")

    settings = {**settings, "media_types": ["tv"]}
    store = Store(tmp_path / "state")
    store.add({**CANDIDATE, "media_type": "series"})
    store.db.commit()
    process_advanced(settings, store, False, metadata=ForbiddenMetadata(), slots=Slots(), inventory=Inventory("hi"))
    assert store.db.execute("SELECT status FROM jobs").fetchone()[0] == "filtered"
    store.db.close()


def test_language_sets_have_independent_canonical_cursors():
    class Store:
        def __init__(self):
            self.keys = []

        def cursor(self, key):
            self.keys.append(key)

        def page(self, *args):
            pass

    class Catalogue:
        def page(self, *args):
            return [], None

    store = Store()
    for languages in [["ta"], ["hi"], ["ta", "te"], ["te", "ta"]]:
        discover({"services": {"netflix": {"region": "US"}}, "pages_per_service": 1, "original_languages": languages}, Catalogue(), store)
    assert store.keys[0] != store.keys[1] and store.keys[2] == store.keys[3]

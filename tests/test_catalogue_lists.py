# ruff: noqa: S101, F401, F811 -- shared pytest fixtures
import json

import pytest
from test_catalogue_state import queue
from test_catalogue_web import auth, browser, client, config, login, post
from test_catalogue_workflow import CANDIDATE, Metadata, Slots, settings

from src.catalogue_lists import SavedLists
from src.catalogue_store import Store
from src.catalogue_workflow import process_advanced


@pytest.mark.parametrize("correct", [True, False])
def test_inventory_only_needs_no_cardinal_and_verifies_identity(settings, tmp_path, correct):
    settings.update(discovery_inventory_only=True, eligibility="absent_all")
    store = Store(tmp_path / "queue.sqlite3")
    store.add(CANDIDATE)
    store.db.commit()

    class Inventory:
        def check_until_hit(self, _imdb):
            return {"HDB": "absent"}

        def _tmdb_identity(self, _imdb, _kind):
            return {"id": 42, "title": CANDIDATE["title"] if correct else "Other movie", "release_date": "2024-01-01"}

    class Forbidden(Metadata):
        def item_profile(self, _candidate):
            raise AssertionError("Discovery-only must not call Cardinal")

    process_advanced(settings, store, False, metadata=Forbidden(), slots=Slots(), inventory=Inventory())
    row = store.db.execute("SELECT status,evidence FROM jobs").fetchone()
    assert row[0] == ("review" if correct else "unknown")
    assert json.loads(row[1])["identity_verified"] is correct
    assert store.db.execute("SELECT count(*) FROM attempts").fetchone()[0] == 0
    store.db.close()


def test_gaps_survive_queue_changes_and_restart(queue, tmp_path):
    store, reader = queue
    store.update("tt0000001", "unavailable", evidence={"inventory": {"HDB": "absent", "PTP": "absent"}})
    lists = SavedLists(reader, tmp_path)
    result = lists.save({"title": "Missing titles"}, ["HDB", "PTP"])
    assert result["total"] == 1
    store.update("tt0000001", "blocked", evidence={"inventory": {"HDB": "present"}})
    restored = SavedLists(reader, tmp_path).page(result["id"])
    assert restored["results"][0]["title_gap"] is True
    assert restored["results"][0]["streaming_ready"] is False
    assert restored["results"][0]["identity_verified"] is False
    assert json.loads((lists.root / (result["id"] + ".json")).read_text())["total"] == 1


def test_unknown_inventory_not_a_gap(queue, tmp_path):
    store, reader = queue
    store.update("tt0000001", "unknown", evidence={"inventory": {"HDB": "absent", "PTP": "unknown"}})
    store.update("tt0000002", "ready")
    assert SavedLists(reader, tmp_path).save({}, ["HDB", "PTP"])["total"] == 0


def test_bounded_indexed_pages_and_literal_search(queue, tmp_path):
    _, reader = queue
    lists = SavedLists(reader, tmp_path)
    result = lists.save({"scope": "all"}, ["HDB"])
    assert result["total"] == 130
    first = lists.page(result["id"], 1, 100)
    second = lists.page(result["id"], 2, 100)
    assert len(first["results"]) == 100 and len(second["results"]) == 30
    assert lists.page(result["id"], query="Movie 130")["total"] == 1
    assert lists.page(result["id"], query="' OR 1=1 --")["total"] == 0
    assert not {r["key"] for r in first["results"]} & {r["key"] for r in second["results"]}
    assert lists.save({"scope": "all", "q": "' OR 1=1 --"}, ["HDB"])["total"] == 0
    with pytest.raises(ValueError):
        lists.page("../../etc/passwd")
    with pytest.raises(ValueError):
        lists.page(result["id"], size=10000)


def test_selected_tracker_changes_and_partial_slot_evidence_fail_closed(queue, tmp_path):
    store, reader = queue
    store.update("tt0000001", "ready", evidence={"trackers": {"HDB": {"state": "absent"}, "PTP": {"state": "unknown"}}})
    assert SavedLists(reader, tmp_path).save({}, ["HDB", "PTP"])["total"] == 0
    store.update("tt0000001", "unavailable", evidence={"inventory": {"HDB": "absent"}})
    assert SavedLists(reader, tmp_path).save({}, ["HDB", "PTP"])["total"] == 0


@pytest.mark.asyncio
async def test_saved_routes_auth_csrf_export(browser):
    assert (await browser.get("/api/lists")).status == 401
    headers = await login(browser)
    assert (await post(browser, "/api/lists", {"title": "Test"}, {})).status == 403
    result = await post(browser, "/api/lists", {"title": "Safe list", "scope": "all"}, headers)
    assert result.status == 200
    identifier = (await result.json())["id"]
    assert (await browser.get("/api/lists/" + identifier)).status == 200
    exported = await browser.get("/api/lists/" + identifier + "/export")
    assert exported.status == 200 and "attachment" in exported.headers["Content-Disposition"]
    assert "results" in await exported.json()

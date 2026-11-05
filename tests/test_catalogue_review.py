# ruff: noqa: S101, F401, F811 -- shared pytest fixtures
import json
import time

import pytest
from test_catalogue_state import queue
from test_catalogue_web import auth, browser, client, config, login, post
from test_catalogue_workflow import CANDIDATE, Metadata, Slots, settings

from src.catalogue_access import access_state, record_access
from src.catalogue_lists import SavedLists
from src.catalogue_review import Review
from src.catalogue_store import Store
from src.catalogue_workflow import process_advanced


def test_manual_access_is_expiring_region_bound_and_not_download_authority(queue):
    store, _reader = queue
    result = record_access(store, "tt0000001", "included")
    candidate = json.loads(store.db.execute("SELECT candidate FROM jobs WHERE job_key=?", ("tt0000001",)).fetchone()[0])
    assert result["source_access"] == "manual_included" and result["download_authorized"] is False
    assert access_state(store.db, candidate, "tt0000001", time.time() + 86500) == "unverified"
    assert access_state(store.db, {**candidate, "region": "GB"}, "tt0000001") == "unverified"
    record_access(store, "tt0000001", "paid")
    assert access_state(store.db, candidate, "tt0000001") == "rent_buy_or_addon"
    assert store.db.execute("SELECT count(*)FROM attempts").fetchone()[0] == 0


@pytest.mark.parametrize("decision", [None, "paid", "included"])
@pytest.mark.parametrize("native", ["included", "unknown", "paid"])
def test_prime_gate_before_tracker_or_provider_requests(settings, tmp_path, decision, native):
    settings.update(require_prime_inclusion=True, eligibility="absent_all", services={"amazon": {"region": "GB", "daily_limit": 1}}, media_types=["movie"])
    store = Store(tmp_path / "queue.sqlite3")
    store.add({**CANDIDATE, "service": "amazon", "region": "GB"})
    store.db.commit()
    if decision:
        record_access(store, CANDIDATE["imdb"], decision)

    class Inventory:
        calls = 0

        def check_until_hit(self, _imdb):
            self.calls += 1
            return {"HDB": "present"}

    inventory = Inventory()

    class NativeUnknown:
        def check(self, _candidate):
            return {"state": native, "reason": "Native subscription fixture"}

    process_advanced(settings, store, False, metadata=Metadata(), slots=Slots(), inventory=inventory, access_probe=NativeUnknown())
    assert inventory.calls == (1 if native == "included" else 0)  # manual notes never bypass automatic verification
    assert store.db.execute("SELECT count(*)FROM attempts").fetchone()[0] == 0
    store.db.close()


def test_more_queue_filters_and_saved_view_are_consistent(queue, tmp_path):
    store, reader = queue
    store.add(
        {
            "imdb": "tt9990001",
            "title": "Special Tamil movie",
            "year": 1999,
            "imdb_votes": 900,
            "original_language": "ta",
            "service": "amazon",
            "region": "GB",
            "item": "B000000001",
        }
    )
    store.db.commit()
    filters = {"year_min": 1990, "year_max": 2000, "min_votes": 500, "language": "ta", "sort": "title"}
    assert reader.page(filters=filters)["total"] == 1
    record_access(store, "tt9990001", "included")
    assert reader.page(filters={**filters, "access": "manual_included"})["total"] == 1
    lists = SavedLists(reader, tmp_path)
    assert lists.save({"scope": "all", "filters": filters}, ["HDB"])["total"] == 1
    with pytest.raises(ValueError):
        reader.page(filters={"sort": "DROP TABLE jobs"})


def test_checklist_persists_without_mutating_snapshot_or_uploading(queue, tmp_path):
    _store, reader = queue
    lists = SavedLists(reader, tmp_path)
    saved = lists.save({"scope": "all"}, ["HDB"])
    original = (lists.root / (saved["id"] + ".json")).read_bytes()
    review = Review(lists, None)
    review.mark(saved["id"], {"positions": [0, 1], "state": "keep", "note": "Verify 1080p and upload manually later"})
    page = lists.page(saved["id"])
    assert page["results"][0]["manual_review"]["state"] == "keep"
    exported = json.loads(review.export(saved["id"]).read_text())
    assert exported["results"][0]["manual_review"]["note"].startswith("Verify 1080p")
    assert (lists.root / (saved["id"] + ".json")).read_bytes() == original
    with pytest.raises(ValueError):
        review.mark(saved["id"], {"positions": [0, 99999], "state": "uploaded"})
    assert lists.page(saved["id"])["results"][0]["manual_review"]["state"] == "keep"


@pytest.mark.asyncio
async def test_presets_validated_and_source_review_requires_explicit_account_check(browser, config):
    headers = await login(browser)
    assert (await browser.get("/api/presets")).status == 200
    bad = await post(browser, "/api/presets", {"name": "Unsafe", "settings": {"allow_downloads": True}}, headers)
    assert bad.status == 400
    saved = await post(browser, "/api/presets", {"name": "Back catalogue", "settings": {"min_release_year": 1980}}, headers)
    assert saved.status == 200
    data = await (await browser.get("/api/presets")).json()
    assert data["presets"][0]["settings"] == {"min_release_year": 1980}
    cfg = json.loads(config.read_text())
    store = Store(__import__("pathlib").Path(cfg["state_dir"]) / "queue.sqlite3")
    store.add({**CANDIDATE, "service": "amazon", "region": "GB"})
    store.db.commit()
    store.db.close()
    body = {"key": CANDIDATE["imdb"], "region": "GB", "decision": "included"}
    assert (await post(browser, "/api/source-review", body, headers)).status == 400
    assert (await post(browser, "/api/source-review", {**body, "checked_in_account": True}, headers)).status == 200
    assert (await post(browser, "/api/presets", {"delete": data["presets"][0]["id"]}, headers)).status == 200

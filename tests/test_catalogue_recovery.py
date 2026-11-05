# ruff: noqa: S101, F401, F811 -- imported pytest fixtures intentionally share parameter names
"""Explicit recovery, immutable budgets, and schedule/configuration races."""

import asyncio
import json
from pathlib import Path

import pytest
from test_catalogue_web import auth, browser, client, config, login, post

from src.catalogue_runner import Store, locked_state
from src.catalogue_web import Dashboard, atomic_json

CANDIDATE = {"imdb": "tt1234567", "title": "Recovery fixture", "year": 2024, "service": "netflix", "region": "US", "item": "123", "origin_countries": ["IN"]}


def seed(config, status="unknown", spent=False):
    cfg = json.loads(config.read_text())
    directory = Path(cfg["state_dir"])
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    store = Store(directory / "queue.sqlite3")
    with store.db:
        store.add(CANDIDATE)
    if spent:
        assert store.reserve(CANDIDATE["imdb"], "netflix", 2, 2)
    store.update(CANDIDATE["imdb"], status, "Offline fixture only")
    return store


@pytest.mark.asyncio
async def test_unstarted_recheck_only_changes_queue(browser, config):
    store = seed(config)
    assert store.db.execute("SELECT next_check FROM jobs").fetchone()[0] > 0
    store.db.close()
    assert (await browser.post("/api/jobs/recheck", json={"job_key": CANDIDATE["imdb"]})).status == 403  # Origin guard runs before session authentication.
    headers = await login(browser)
    response = await post(browser, "/api/jobs/recheck", {"job_key": CANDIDATE["imdb"]}, headers)
    assert response.status == 200 and "no API requests" in (await response.json())["message"]
    cfg = json.loads(config.read_text())
    store = Store(Path(cfg["state_dir"]) / "queue.sqlite3")
    assert tuple(store.db.execute("SELECT status,next_check FROM jobs").fetchone()) == ("pending", 0)
    assert store.usage()[0] == 0
    store.db.close()


@pytest.mark.asyncio
async def test_failed_retry_requires_typed_verification_and_retains_spend(browser, config):
    seed(config, "failed", spent=True).db.close()
    headers = await login(browser)
    assert (await post(browser, "/api/jobs/recheck", {"job_key": CANDIDATE["imdb"]}, headers)).status == 400
    response = await post(browser, "/api/jobs/recheck", {"job_key": CANDIDATE["imdb"], "confirmation": "VERIFIED NO PAYLOAD"}, headers)
    assert response.status == 200
    cfg = json.loads(config.read_text())
    store = Store(Path(cfg["state_dir"]) / "queue.sqlite3")
    assert store.usage()[0] == 1
    assert not store.reserve(CANDIDATE["imdb"], "netflix", 1, 1)
    store.db.close()


@pytest.mark.parametrize("status", ["started", "succeeded"])
@pytest.mark.asyncio
async def test_in_flight_and_completed_jobs_are_not_replayable(browser, config, status):
    seed(config, status, spent=True).db.close()
    headers = await login(browser)
    response = await post(browser, "/api/jobs/recheck", {"job_key": CANDIDATE["imdb"], "confirmation": "VERIFIED NO PAYLOAD"}, headers)
    assert response.status == 400


@pytest.mark.asyncio
async def test_rule_changes_invalidate_only_unstarted_jobs(browser, config):
    store = seed(config, "ready")
    with store.db:
        store.add({**CANDIDATE, "imdb": "tt7654321"})
    assert store.reserve("tt7654321", "netflix", 2, 2)
    store.update("tt7654321", "failed", "Fixture")
    store.db.close()
    headers = await login(browser)
    response = await post(browser, "/api/settings", {"settings": {"origin_countries": ["GB"]}}, headers)
    assert response.status == 200
    cfg = json.loads(config.read_text())
    store = Store(Path(cfg["state_dir"]) / "queue.sqlite3")
    assert dict(store.db.execute("SELECT job_key,status FROM jobs")) == {"tt1234567": "pending", "tt7654321": "failed"}
    assert store.usage()[0] == 1
    store.db.close()


@pytest.mark.asyncio
async def test_settings_do_not_race_standalone_runner(browser, config):
    before = config.read_bytes()
    headers = await login(browser)
    with locked_state(Path(json.loads(before)["state_dir"])):
        response = await post(browser, "/api/settings", {"settings": {"daily_limit": 9}}, headers)
    assert response.status == 400 and config.read_bytes() == before


@pytest.mark.asyncio
async def test_disabled_schedule_cannot_launch_after_waiting_for_settings(config, auth, monkeypatch):
    cfg = json.loads(config.read_text())
    atomic_json(config, {**cfg, "schedule": {"enabled": True, "mode": "plan", "interval_minutes": 60}})
    dashboard = Dashboard(config, auth)

    async def forbidden(*_args):
        pytest.fail("Paused scheduler launched a worker")

    monkeypatch.setattr(dashboard, "run_worker", forbidden)
    async with dashboard.action_lock:
        launch = asyncio.create_task(dashboard.start(scheduled=True))
        await asyncio.sleep(0)
        atomic_json(config, cfg)
    await launch
    assert dashboard.worker_task is None

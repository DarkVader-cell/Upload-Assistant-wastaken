# ruff: noqa: S101
"""Dedicated dashboard contracts; all APIs and downloads are mocked."""

import asyncio
import json
import subprocess
from pathlib import Path

import pytest
import pytest_asyncio
from aiohttp import CookieJar
from aiohttp.test_utils import TestClient, TestServer

from src.catalogue_runner import DOCKER_SUPERVISOR, Store, cardinal_argv, download
from src.catalogue_web import CONFIRM, COOKIE, DASHBOARD_KEY, Dashboard, atomic_json, create_app, password_record, verify_password


@pytest.fixture
def config(tmp_path):
    ua = tmp_path / "ua.py"
    ua.write_text("config = {'TRACKERS': {'HDBITS': {'username': 'private-user', 'passkey': 'private-key'}}}")
    path = tmp_path / "runner.json"
    atomic_json(
        path,
        {
            "ua_config": str(ua),
            "state_dir": str(tmp_path / "state"),
            "cardinal_binary": "/private/cardinaldl",
            "cardinal_configpath": "/private/cardinal/storage.db",
            "services": {"netflix": {"region": "US", "daily_limit": 2}},
            "trackers": ["HDB"],
            "origin_countries": ["IN"],
            "daily_limit": 2,
            "allow_downloads": False,
            "schedule": {"enabled": False, "mode": "plan", "interval_minutes": 60},
        },
    )
    return path


@pytest.fixture
def auth(tmp_path):
    path = tmp_path / "auth.json"
    atomic_json(path, password_record("test-secret"))
    return path


@pytest.fixture
def client(config, auth):
    async def make():
        c = TestClient(TestServer(create_app(config, auth)), cookie_jar=CookieJar(unsafe=True))
        await c.start_server()
        return c

    # Fixture body is async below through a generator helper.
    return make


@pytest_asyncio.fixture
async def browser(client):
    c = await client()
    yield c
    await c.close()


def origin(client):
    return str(client.make_url("/")).rstrip("/")


async def login(client):
    response = await client.post("/api/login", json={"password": "test-secret"}, headers={"Origin": origin(client)})
    assert response.status == 200
    data = await response.json()
    return {"Origin": origin(client), "X-CSRF-Token": data["csrf"]}


async def post(client, endpoint, body, headers):
    return await client.post(endpoint, json=body, headers=headers)


@pytest.mark.asyncio
async def test_login_cookie_auth_logout(browser):
    response = await browser.get("/api/status")
    assert response.status == 401
    headers = await login(browser)
    assert browser.session.cookie_jar.filter_cookies(browser.make_url("/"))[COOKIE].value
    response = await browser.get("/api/status")
    data = await response.json()
    assert data["runtime"] == "dedicated host" and not data["busy"]
    assert data["capabilities"]["existing_title_slots"] is True
    assert data["capabilities"]["tracker_apis_verified"] is False
    assert data["capabilities"]["metadata_adapter_configured"] is False
    text = json.dumps(data)
    assert "private-key" not in text and "private-user" not in text and "storage.db" not in text
    assert (await post(browser, "/api/logout", {}, headers)).status == 200
    assert (await browser.get("/api/status")).status == 401


@pytest.mark.asyncio
async def test_csrf_and_origin_are_required(browser):
    assert (await browser.post("/api/login", json={"password": "test-secret"})).status == 403
    headers = await login(browser)
    assert (await post(browser, "/api/pause", {}, {"Origin": origin(browser)})).status == 403
    assert (await post(browser, "/api/pause", {}, {**headers, "Origin": "https://evil.invalid"})).status == 403
    assert (await post(browser, "/api/pause", {}, headers)).status == 200


@pytest.mark.asyncio
async def test_invalid_password_and_throttle(browser):
    for _ in range(5):
        response = await post(browser, "/api/login", {"password": "wrong"}, {"Origin": origin(browser)})
        assert response.status == 401
    response = await post(browser, "/api/login", {"password": "test-secret"}, {"Origin": origin(browser)})
    assert response.status == 429


@pytest.mark.asyncio
async def test_password_input_and_malformed_json(browser):
    headers = {"Origin": origin(browser)}
    assert (await post(browser, "/api/login", [], headers)).status == 400
    assert (await post(browser, "/api/login", {"password": {}}, headers)).status == 400
    assert (await post(browser, "/api/login", {"password": "x" * 513}, headers)).status == 400


@pytest.mark.asyncio
async def test_settings_save_backup_and_server_path_protection(browser, config):
    headers = await login(browser)
    response = await post(browser, "/api/settings", {"settings": {"daily_limit": 7, "origin_countries": ["JP"]}}, headers)
    assert response.status == 200
    data = json.loads(config.read_text())
    assert data["daily_limit"] == 7 and data["origin_countries"] == ["JP"]
    assert list(config.parent.glob("runner.json.bak-*"))
    assert config.stat().st_mode & 0o077 == 0
    for update in [
        {"ua_config": "/not-allowed/evil.py"},
        {"cardinal_binary": "sh"},
        {"services": {"netflix": {"configpath": "/not-allowed/evil"}}},
        {"daily_limit": -1},
        {"trackers": []},
        {"origin_countries": ["India"]},
    ]:
        assert (await post(browser, "/api/settings", {"settings": update}, headers)).status == 400
    assert json.loads(config.read_text())["daily_limit"] == 7


@pytest.mark.asyncio
async def test_execution_and_schedule_require_explicit_confirmation(browser, config):
    headers = await login(browser)
    for body in [
        {"settings": {"allow_downloads": True}},
        {"settings": {"schedule": {"enabled": True, "interval_minutes": 1}}},
        {"settings": {"schedule": {"enabled": True, "mode": "execute", "interval_minutes": 60}}},
    ]:
        assert (await post(browser, "/api/settings", body, headers)).status == 400
    assert (await post(browser, "/api/run", {"mode": "execute", "confirmation": CONFIRM}, headers)).status == 409
    assert (await post(browser, "/api/settings", {"settings": {"allow_downloads": True}, "confirmation": CONFIRM}, headers)).status == 200
    assert (await post(browser, "/api/run", {"mode": "execute"}, headers)).status == 400
    assert json.loads(config.read_text())["allow_downloads"] is True


@pytest.mark.asyncio
async def test_start_busy_pause_and_cancel_use_owned_process_only(browser, monkeypatch, config):
    headers = await login(browser)
    dashboard = browser.app[DASHBOARD_KEY]
    gate = asyncio.Event()
    signals = []

    class Child:
        def send_signal(self, sig):
            signals.append(sig)
            gate.set()

    async def worker(_execute, _queue_only):
        dashboard.process = Child()
        await gate.wait()
        dashboard.process = None

    monkeypatch.setattr(dashboard, "run_worker", worker)
    assert (await post(browser, "/api/run", {"mode": "plan"}, headers)).status == 202
    await asyncio.sleep(0)
    assert (await post(browser, "/api/run", {"mode": "plan"}, headers)).status == 409
    assert (await post(browser, "/api/settings", {"settings": {"daily_limit": 3}}, headers)).status == 409
    assert (await post(browser, "/api/pause", {}, headers)).status == 200
    assert (await post(browser, "/api/cancel", {"pid": 1}, headers)).status == 200
    await dashboard.worker_task
    assert len(signals) == 1
    assert json.loads(config.read_text())["schedule"]["enabled"] is False


@pytest.mark.asyncio
async def test_queue_is_read_only_and_xss_values_are_data(browser, config):
    state = Path(json.loads(config.read_text())["state_dir"])
    state.mkdir(mode=0o700)
    store = Store(state / "queue.sqlite3")
    store.page("key", [{"imdb": "tt1234567", "service": "netflix", "region": "US", "item": "1", "title": "<script>alert(1)</script>"}], None)
    store.db.close()
    await login(browser)
    data = await (await browser.get("/api/status")).json()
    assert data["queue"]["jobs"][0]["title"] == "<script>alert(1)</script>"
    response = await browser.get("/app.js")
    script = await response.text()
    assert "innerHTML" not in script
    assert "textContent" in script


@pytest.mark.asyncio
async def test_assets_and_security_headers(browser):
    for path in ["/", "/app.js", "/style.css"]:
        response = await browser.get(path)
        assert response.status == 200
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
        assert response.headers["Cache-Control"] == "no-store"
    assert (await browser.get("/../runner.json")).status == 404


@pytest.mark.asyncio
async def test_status_never_automatically_calls_apis_or_cardinal(browser, monkeypatch):
    async def forbidden(*_args, **_kwargs):
        pytest.fail("automatic process/API call")

    monkeypatch.setattr("src.catalogue_web.asyncio.create_subprocess_exec", forbidden)
    await login(browser)
    for _ in range(3):
        assert (await browser.get("/api/status")).status == 200


@pytest.mark.asyncio
async def test_cardinal_health_native_fake_executable(config, auth, tmp_path, monkeypatch):
    import asyncio

    original_wait = asyncio.wait_for
    deadlines = []

    async def measured_wait(awaitable, timeout):  # noqa: ASYNC109 -- spy mirrors asyncio.wait_for's signature
        deadlines.append(timeout)
        return await original_wait(awaitable, timeout=timeout)

    monkeypatch.setattr(asyncio, "wait_for", measured_wait)
    fake = tmp_path / "fake-cardinal"
    fake.write_text("#!/bin/sh\nprintf '3.10.16\\n'\n")
    fake.chmod(0o700)
    cfg = json.loads(config.read_text())
    cfg["cardinal_binary"] = str(fake)
    atomic_json(config, cfg)
    result = await Dashboard(config, auth).health()
    assert result["ok"] and result["version"] == "3.10.16"
    assert 50 in deadlines  # Allow measured slow startup, never an unbounded probe.
    fake.write_text("#!/bin/sh\nprintf 'private-token\\n'\n")
    result = await Dashboard(config, auth).health()
    assert result["ok"] is False and result["version"] is None
    assert "private-token" not in json.dumps(result)


@pytest.mark.asyncio
async def test_scheduler_launches_only_explicitly_enabled_mode(config, auth, monkeypatch):
    cfg = json.loads(config.read_text())
    cfg["schedule"] = {"enabled": True, "mode": "plan", "interval_minutes": 60}
    atomic_json(config, cfg)
    dashboard = Dashboard(config, auth)
    calls = []

    async def start(execute=False, scheduled=False):
        assert scheduled
        calls.append(execute)

    async def once(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(dashboard, "start", start)
    monkeypatch.setattr("src.catalogue_web.asyncio.sleep", once)
    with pytest.raises(asyncio.CancelledError):
        await dashboard.scheduler()
    assert calls == [False]
    cfg["schedule"]["enabled"] = False
    atomic_json(config, cfg)
    calls.clear()
    with pytest.raises(asyncio.CancelledError):
        await dashboard.scheduler()
    assert not calls


@pytest.mark.asyncio
async def test_expired_session_is_rejected(browser):
    await login(browser)
    dashboard = browser.app[DASHBOARD_KEY]
    for key, (_, csrf) in list(dashboard.sessions.items()):
        dashboard.sessions[key] = (0, csrf)
    assert (await browser.get("/api/status")).status == 401


@pytest.mark.asyncio
async def test_light_status_and_paginated_queue_api(browser, config):
    state = Path(json.loads(config.read_text())["state_dir"])
    state.mkdir(mode=0o700)
    store = Store(state / "queue.sqlite3")
    store.page("seed", [{"imdb": f"tt{index:07}", "title": f"Fixture {index}", "service": "netflix", "region": "US", "item": str(index)} for index in range(1, 62)], None)
    store.db.close()
    await login(browser)
    response = await browser.get("/api/status?include_queue=0")
    body = await response.json()
    assert body["queue"]["jobs"] == [] and body["queue"]["total"] == 61
    assert len(json.dumps(body)) < 5000
    result = await (await browser.get("/api/queue?page=2&page_size=25&service=netflix")).json()
    assert result["total"] == 61 and result["pages"] == 3 and len(result["jobs"]) == 25
    assert (await browser.get("/api/queue?page_size=999999")).status == 400
    assert (await browser.get("/api/queue?status=invalid")).status == 400
    assert (await browser.get("/api/queue?sql=select")).status == 400
    assert (await browser.get("/api/status?include_queue=maybe")).status == 400


def test_password_hash_is_salted_and_not_plaintext():
    record = password_record("test-secret")
    assert verify_password("test-secret", record)
    assert not verify_password("wrong", record)
    assert "test-secret" not in json.dumps(record)
    assert record != password_record("test-secret")


def test_docker_adapter_uses_container_paths_and_supervisor():
    cfg = {"cardinal_docker": {"container": "cardinal-test"}, "timeout_seconds": 10, "cardinal_configpath": "/config/storage/storage.db"}
    args = cardinal_argv(cfg, ["--version"])
    assert args[:8] == ["docker", "exec", "--interactive", "--user", "node", "--workdir", "/app/.output", "cardinal-test"]
    assert DOCKER_SUPERVISOR in args and args[-3:] == ["--configpath", "/config/storage/storage.db", "--version"]
    assert "sh" not in args and "-c" not in args
    assert "process.kill(-child.pid" in DOCKER_SUPERVISOR


def test_docker_cancel_waits_for_container_eof_before_signalling_client(monkeypatch):
    class Input:
        closed = False

        def close(self):
            self.closed = True

    class Child:
        stdin = Input()
        waits = 0

        def wait(self, timeout):
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("docker", timeout)
            assert self.stdin.closed
            return 124

    monkeypatch.setattr("src.catalogue_runner.subprocess.Popen", lambda *_a, **_kw: Child())
    monkeypatch.setattr("src.catalogue_runner.os.killpg", lambda *_a: pytest.fail("client signalled before container EOF cleanup"))
    assert download(["docker", DOCKER_SUPERVISOR], 1) == "uncertain"


def test_download_stdin_is_kept_open_until_child_finishes(monkeypatch):
    class Input:
        closed = False

        def close(self):
            self.closed = True

    class Child:
        stdin = Input()

        def wait(self, timeout):
            assert timeout == 5
            assert not self.stdin.closed
            return 0

    child = Child()

    def spawn(_command, **kwargs):
        assert kwargs["stdin"] == subprocess.PIPE
        return child

    monkeypatch.setattr("src.catalogue_runner.subprocess.Popen", spawn)
    assert download(["fake"], 5) == "succeeded"
    assert child.stdin.closed

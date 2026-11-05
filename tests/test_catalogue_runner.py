# ruff: noqa: S101
"""Offline safety/contract tests: no real tracker calls or downloads."""

import json
import signal
import subprocess
import time

import httpx
import pytest

from src.catalogue_runner import (
    API,
    Catalogue,
    RunnerError,
    Store,
    Trackers,
    cardinal_command,
    discover,
    download,
    load_settings,
    locked_state,
    main,
    process,
    provider_id,
    utc_day,
)


@pytest.fixture
def candidate():
    return {"imdb": "tt1234567", "service": "netflix", "region": "US", "item": "12345", "title": "Test Movie", "year": 2024, "origin_countries": ["IN"]}


@pytest.fixture
def settings(tmp_path):
    return {
        "services": {"netflix": {"region": "US"}},
        "origin_countries": ["IN"],
        "trackers": ["HDB", "PTP", "ATH", "DT"],
        "pages_per_service": 1,
        "daily_limit": 2,
        "max_downloads_per_run": 2,
        "max_checks_per_run": 20,
        "max_candidate_age_hours": 24,
        "min_free_gib": 0,
        "disk_path": str(tmp_path),
        "timeout_seconds": 5,
        "cardinal_binary": "cardinaldl",
    }


@pytest.fixture
def ua():
    return {
        "DEFAULT": {"tmdb_api": "private-tmdb"},
        "TRACKERS": {
            "HDBITS": {"username": "user", "passkey": "private-hdb"},
            "PASSTHEPOPCORN": {"ApiUser": "user", "api_key": "private-ptp"},
            "AITHER": {"api_key": "private-ath"},
            "DESITORRENTS": {"api_key": "private-dt"},
        },
    }


def api_with(payload, status=200, requests=None):
    def handle(request):
        if requests is not None:
            requests.append(request)
        return httpx.Response(status, json=payload)

    return API(httpx.Client(transport=httpx.MockTransport(handle)), interval=0)


def catalogue_page(url="https://www.netflix.com/title/12345", imdb="tt1234567", next_cursor=None):
    return {
        "data": {
            "popularTitles": {
                "pageInfo": {"endCursor": next_cursor, "hasNextPage": next_cursor is not None},
                "edges": [
                    {
                        "node": {
                            "id": "tm1",
                            "objectType": "MOVIE",
                            "content": {"title": "Test", "originalReleaseYear": 2024, "externalIds": {"imdbId": imdb}},
                            "offers": [{"monetizationType": "FLATRATE", "standardWebURL": url, "package": {"shortName": "nfx"}}],
                        }
                    }
                ],
            }
        }
    }


@pytest.mark.parametrize(
    "service,url,expected",
    [
        ("netflix", "https://www.netflix.com/gb/title/12345?x=y", "12345"),
        ("netflix", "https://netflix.com/watch/12345", "12345"),
        ("appletv", "https://tv.apple.com/us/movie/name/umc.cmc.abc123", "umc.cmc.abc123"),
        ("amazon", "https://www.amazon.co.uk/gp/video/detail/B012345678", "B012345678"),
        ("amazon", "https://watch.amazon.co.uk/detail?gti=amzn1.dv.gti.666cea52-0088-49ef-97c2-fae9d22cdae8", "amzn1.dv.gti.666cea52-0088-49ef-97c2-fae9d22cdae8"),
        ("netflix", "https://www.netflix.com.evil.test/title/12345", None),
        ("netflix", "https://netflix.com@evil.test/title/12345", None),
        ("netflix", "http://netflix.com/title/12345", None),
        ("netflix", "https://netflix.com/title/12345;touch", None),
        ("amazon", "https://amazon.co.uk/detail?gti=--login", None),
        ("amazon", "https://amazon.de/dp/B012345678", None),
    ],
)
def test_provider_ids(service, url, expected):
    assert provider_id(service, url) == expected


def test_catalogue_country_region_and_subscription_filters():
    requests = []
    cat = Catalogue(api_with(catalogue_page(), requests=requests))
    candidates, cursor = cat.page("netflix", "US", ["IN"], None)
    assert candidates[0]["item"] == "12345"
    assert candidates[0]["origin_countries"] == ["IN"]
    assert cursor is None
    variables = json.loads(requests[0].content)["variables"]
    assert variables["country"] == "US"
    assert variables["filter"]["productionCountries"] == ["IN"]
    assert variables["filter"]["monetizationTypes"] == ["FLATRATE"]


@pytest.mark.parametrize("imdb", [None, "", "1234567", "tt1"])
def test_no_identity_is_not_download_candidate(imdb):
    assert Catalogue(api_with(catalogue_page(imdb=imdb))).page("netflix", "US", [], None)[0] == []


def test_rentals_and_multiple_editions_skipped():
    data = catalogue_page()
    offers = data["data"]["popularTitles"]["edges"][0]["node"]["offers"]
    offers[0]["monetizationType"] = "RENT"
    assert Catalogue(api_with(data)).page("netflix", "US", [], None)[0] == []
    offers[0]["monetizationType"] = "FLATRATE"
    offers.append({**offers[0], "standardWebURL": "https://netflix.com/title/99999"})
    assert Catalogue(api_with(data)).page("netflix", "US", [], None)[0] == []


@pytest.mark.parametrize("payload", [{}, {"errors": [{"message": "bad"}]}, {"data": {"popularTitles": {"edges": []}}}])
def test_catalogue_errors_block(payload):
    with pytest.raises(RunnerError):
        Catalogue(api_with(payload)).page("netflix", "US", [], None)


def test_repeated_cursor_rejected():
    with pytest.raises(RunnerError):
        Catalogue(api_with(catalogue_page(next_cursor="same"))).page("netflix", "US", [], "same")


@pytest.mark.parametrize(
    "alias,payload,absent",
    [
        ("HDB", {"status": 0, "data": []}, True),
        ("HDB", {"status": 0, "data": [{"id": 1}]}, False),
        ("PTP", {"TotalResults": "0", "Movies": []}, True),
        ("PTP", {"Page": "Browse", "Movies": []}, True),
        ("PTP", {"Page": "Details", "GroupId": "42"}, False),
        ("PTP", {"TotalResults": 2}, False),
        ("ATH", {"data": [], "links": {"next": None}, "meta": {"total": 0}}, True),
        ("DT", {"data": [{"id": 1}]}, False),
    ],
)
def test_tracker_inventory(alias, payload, absent, ua):
    requests = []
    checker = Trackers(api_with(payload, requests=requests), ua, [alias])
    assert checker.absent(alias, "tt1234567", 123) is absent
    req = requests[0]
    assert "resolutions" not in str(req.url) and "types" not in str(req.url)
    assert "category" not in req.content.decode() if alias == "HDB" else True
    if alias == "ATH":
        assert req.headers["authorization"] == "Bearer private-ath"
        assert req.url.params["tmdbId"] == "123"


@pytest.mark.parametrize(
    "alias,payload",
    [
        ("HDB", {}),
        ("HDB", {"status": 1, "data": []}),
        ("PTP", {"TotalResults": 0}),
        ("PTP", {"Error": "bad", "Movies": [], "TotalResults": 0}),
        ("PTP", {"TotalResults": True, "Movies": []}),
        ("ATH", {"data": []}),
        ("DT", {"data": [], "links": {"next": "https://evil.test/"}}),
        ("ATH", {"data": [], "links": {"next": None}, "meta": {"total": 3}}),
        ("DT", {"success": False, "data": [], "links": {"next": None}}),
    ],
)
def test_unknown_inventory_never_absent(alias, payload, ua):
    with pytest.raises(RunnerError):
        Trackers(api_with(payload), ua, [alias]).absent(alias, "tt1234567", 123)


@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
def test_http_errors_do_not_leak_credentials(status):
    with pytest.raises(RunnerError) as error:
        api_with({}, status=status).request("GET", "https://test.invalid/?api_key=secret")
    assert "secret" not in str(error.value)


def test_tmdb_requires_unique_identity(ua):
    with pytest.raises(RunnerError):
        Trackers(api_with({"movie_results": []}), ua, ["ATH"]).check("tt1234567")
    assert Trackers(api_with({"movie_results": [{"id": 42}]}), ua, []).tmdb_movie("tt1234567") == 42


@pytest.fixture
def store(tmp_path):
    instance = Store(tmp_path / "queue.db")
    yield instance
    instance.db.close()


def add(store, candidate):
    store.page("key", [candidate], None)


def status(store):
    return store.db.execute("SELECT status FROM jobs").fetchone()[0]


class FakeTrackers:
    def __init__(self, result=None):
        self.result = result or {"HDB": "absent", "PTP": "absent", "ATH": "absent", "DT": "absent"}
        self.calls = 0

    def check(self, _imdb):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_dry_run_never_calls_cardinal(store, candidate, settings, monkeypatch):
    add(store, candidate)
    monkeypatch.setattr("src.catalogue_runner.download", lambda *_: pytest.fail("download in dry run"))
    process(settings, FakeTrackers(), store, False)
    assert status(store) == "ready"
    assert store.db.execute("SELECT started_day FROM jobs").fetchone()[0] is None


@pytest.mark.parametrize("result,expected", [({"HDB": "present"}, "blocked"), (RunnerError("unknown"), "unknown")])
def test_present_or_unknown_never_launches(store, candidate, settings, monkeypatch, result, expected):
    add(store, candidate)
    monkeypatch.setattr("src.catalogue_runner.download", lambda *_: pytest.fail("unsafe launch"))
    process(settings, FakeTrackers(result), store, True)
    assert status(store) == expected


def test_download_rechecks_plan_and_deduplicates_services(store, candidate, settings, monkeypatch):
    add(store, candidate)
    checker = FakeTrackers()
    process(settings, checker, store, False)
    calls = []
    monkeypatch.setattr("src.catalogue_runner.download", lambda *args: calls.append(args) or "succeeded")
    process(settings, checker, store, True)
    assert len(calls) == 1 and checker.calls == 2
    assert status(store) == "succeeded"
    add(store, {**candidate, "service": "amazon"})
    process(settings, checker, store, True)
    assert len(calls) == 1
    assert store.db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1


def test_daily_limit_counts_failed_or_crashed_starts(store, candidate, settings, monkeypatch):
    add(store, candidate)
    add(store, {**candidate, "imdb": "tt7654321"})
    settings["daily_limit"] = 1
    calls = []
    monkeypatch.setattr("src.catalogue_runner.download", lambda *args: calls.append(args) or "failed")
    process(settings, FakeTrackers(), store, True)
    process(settings, FakeTrackers(), store, True)
    assert len(calls) == 1
    assert store.db.execute("SELECT count(*) FROM jobs WHERE started_day=?", (utc_day(),)).fetchone()[0] == 1


def test_started_jobs_are_never_automatically_replayed(store, candidate, settings, monkeypatch):
    add(store, candidate)
    assert store.reserve(candidate["imdb"], "netflix", 3, 3)
    add(store, candidate)
    monkeypatch.setattr("src.catalogue_runner.download", lambda *_: pytest.fail("crash replay"))
    process(settings, FakeTrackers(), store, True)
    assert status(store) == "started"


def test_per_service_limit_and_zero_limit(store, candidate):
    add(store, candidate)
    assert not store.reserve(candidate["imdb"], "netflix", 2, 0)
    assert not store.reserve(candidate["imdb"], "netflix", 0, 2)
    assert store.reserve(candidate["imdb"], "netflix", 2, 2)
    assert not store.reserve(candidate["imdb"], "netflix", 2, 2)


def test_stale_and_changed_filters_do_not_launch(store, candidate, settings):
    add(store, candidate)
    checker = FakeTrackers()
    settings["origin_countries"] = ["JP"]
    process(settings, checker, store, True)
    assert checker.calls == 0
    settings["origin_countries"] = ["IN"]
    with store.db:
        store.db.execute("UPDATE jobs SET discovered=?", (time.time() - 90000,))
    process(settings, checker, store, True)
    assert status(store) == "stale" and checker.calls == 0
    add(store, candidate)
    assert status(store) == "pending"


def test_disk_guard_and_check_limit(store, candidate, settings, monkeypatch):
    add(store, candidate)
    add(store, {**candidate, "imdb": "tt7654321"})
    settings["max_checks_per_run"] = 1
    checker = FakeTrackers()
    process(settings, checker, store, False)
    assert checker.calls == 1
    settings["min_free_gib"] = 10**10
    monkeypatch.setattr("src.catalogue_runner.download", lambda *_: pytest.fail("disk guard"))
    process(settings, FakeTrackers(), store, True)
    assert store.db.execute("SELECT count(*) FROM jobs WHERE started_day IS NOT NULL").fetchone()[0] == 0


def test_discovery_persists_cursor(settings, store):
    catalogue = Catalogue(api_with(catalogue_page(next_cursor="next")))
    discover(settings, catalogue, store)
    assert store.db.execute("SELECT cursor FROM cursors").fetchone()[0] == "next"
    assert store.db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1


def test_command_only_selects_id_service_and_history(settings, candidate):
    settings["cardinal_configpath"] = "/private/storage.db"
    assert cardinal_command(settings, candidate) == ["cardinaldl", "--configpath", "/private/storage.db", "--service", "netflix", "--item", "12345", "--save-to-history"]


def test_fake_cardinal_subprocess(tmp_path):
    # Exercise actual process execution without any network access.
    fake = tmp_path / "fake-cardinal"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o700)
    assert download([str(fake), "--item", "123"], 5) == "succeeded"
    fake.write_text("#!/bin/sh\nexit 1\n")
    assert download([str(fake)], 5) == "failed"
    fake.write_text("#!/bin/sh\nexit 124\n")
    assert download([str(fake)], 5) == "uncertain"
    assert download([str(tmp_path / "absent")], 5) == "failed"


def test_timeout_terminates_only_child_group(monkeypatch):
    class Child:
        pid = 987654
        waits = 0
        stdin = None

        def wait(self, timeout=None):
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("fake", timeout)
            return -15

    signals = []
    monkeypatch.setattr("src.catalogue_runner.subprocess.Popen", lambda *_a, **_k: Child())
    monkeypatch.setattr("src.catalogue_runner.os.killpg", lambda pid, sig: signals.append((pid, sig)))
    assert download(["fake"], 1) == "uncertain"
    assert signals == [(987654, signal.SIGTERM)]


def test_lock_and_private_directory(tmp_path):
    state = tmp_path / "state"
    with locked_state(state), pytest.raises(RunnerError), locked_state(state):
        pass
    state.chmod(0o755)
    with pytest.raises(RunnerError), locked_state(state):
        pass


def test_config_validates_without_showing_secrets(tmp_path, ua):
    ua_file = tmp_path / "ua.py"
    ua_file.write_text("config = " + repr(ua))
    path = tmp_path / "runner.json"
    settings = {"ua_config": str(ua_file), "services": {"netflix": {}}, "trackers": ["HDB"]}
    path.write_text(json.dumps(settings))
    config, loaded = load_settings(path)
    assert config["daily_limit"] == 5 and loaded == ua
    for change in [{"eligibility": "free_slots"}, {"daily_limit": -1}, {"daily_limit": True}, {"trackers": []}, {"services": {"other": {}}}, {"origin_countries": ["India"]}]:
        path.write_text(json.dumps({**settings, **change}))
        with pytest.raises(RunnerError):
            load_settings(path)
    path.write_text(json.dumps(settings))
    assert main(["--config", str(path), "--execute"]) == 1


def test_partial_absence_cannot_authorize_download(store, candidate, settings, monkeypatch):
    add(store, candidate)
    monkeypatch.setattr("src.catalogue_runner.download", lambda *_: pytest.fail("incomplete evidence"))
    process(settings, FakeTrackers({"HDB": "absent"}), store, True)
    assert status(store) == "blocked"


def test_offline_end_to_end_cli(tmp_path, ua, monkeypatch):
    ua_file = tmp_path / "ua.py"
    ua_file.write_text("config = " + repr(ua))
    fake = tmp_path / "fake cardinal"
    marker = tmp_path / "executions"
    fake.write_text(f"#!/bin/sh\nprintf '%s\\n' ran >> '{marker}'\nexit 0\n")
    fake.chmod(0o700)
    cfg = tmp_path / "runner.json"
    cfg.write_text(
        json.dumps(
            {
                "ua_config": str(ua_file),
                "state_dir": str(tmp_path / "state"),
                "services": {"netflix": {"region": "US"}},
                "origin_countries": ["IN"],
                "cardinal_binary": str(fake),
                "allow_downloads": True,
                "disk_path": str(tmp_path),
                "min_free_gib": 0,
            }
        )
    )
    requests = []

    def handle(request):
        requests.append(request)
        host = request.url.host
        if host == "apis.justwatch.com":
            return httpx.Response(200, json=catalogue_page())
        if host == "api.themoviedb.org":
            return httpx.Response(200, json={"movie_results": [{"id": 42}]})
        if host == "hdbits.org":
            return httpx.Response(200, json={"status": 0, "data": []})
        if host == "passthepopcorn.me":
            return httpx.Response(200, json={"TotalResults": 0, "Movies": []})
        if host in {"aither.cc", "torrent.desi"}:
            return httpx.Response(200, json={"data": [], "links": {"next": None}})
        pytest.fail("unexpected network target")

    real_client = httpx.Client
    monkeypatch.setattr("src.catalogue_runner.httpx.Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs))
    monkeypatch.setattr("src.catalogue_runner.time.sleep", lambda _: None)
    assert main(["--config", str(cfg)]) == 0
    assert not marker.exists()
    assert main(["--config", str(cfg), "--execute", "--queue-only"]) == 0
    assert marker.read_text() == "ran\n"
    assert main(["--config", str(cfg), "--execute", "--queue-only"]) == 0
    assert marker.read_text() == "ran\n"
    assert sum(r.url.host == "hdbits.org" for r in requests) == 2


@pytest.mark.parametrize("rows", [[None], ["invalid"], [{"id": True}], [{"id": 0}]])
def test_malformed_tmdb_identity_blocks(rows, ua):
    with pytest.raises(RunnerError):
        Trackers(api_with({"movie_results": rows}), ua, []).tmdb_movie("tt1234567")


def test_unknown_jobs_do_not_starve_unchecked_queue(store, candidate, settings):
    add(store, candidate)
    add(store, {**candidate, "imdb": "tt7654321"})
    settings["max_checks_per_run"] = 1
    process(settings, FakeTrackers(RunnerError("temporary failure")), store, False)
    process(settings, FakeTrackers(), store, False)
    rows = dict(store.db.execute("SELECT imdb,status FROM jobs").fetchall())
    assert rows == {"tt1234567": "unknown", "tt7654321": "ready"}


def test_scope_filtering_happens_before_the_bounded_work_limit(store, candidate, settings):
    add(store, {**candidate, "imdb": "tt1111111", "region": "DE"})
    add(store, {**candidate, "imdb": "tt2222222", "origin_countries": ["JP"]})
    add(store, candidate)
    settings["max_checks_per_run"] = 1
    checker = FakeTrackers()
    process(settings, checker, store, False)
    rows = dict(store.db.execute("SELECT imdb,status FROM jobs").fetchall())
    assert checker.calls == 1
    assert rows == {"tt1111111": "pending", "tt2222222": "pending", "tt1234567": "ready"}


def test_python311_syntax():
    import ast
    from pathlib import Path

    for name in ("src/catalogue_runner.py", "src/catalogue_web.py", "tools/catalogue-runner.py"):
        ast.parse(Path(name).read_text(), feature_version=(3, 11))

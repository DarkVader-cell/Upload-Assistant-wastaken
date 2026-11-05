# ruff: noqa: S101
"""PTP redirects remain API-only, same-site, bounded, and independently paced."""

import httpx
import pytest

from src.catalogue_rate import APIPacer, ptp_api_redirect
from src.catalogue_runner import API, RunnerError


@pytest.mark.parametrize(
    "location",
    [
        "https://evil.example/torrents.php?id=1",
        "http://passthepopcorn.me/torrents.php?id=1",
        "/login.php",
        "/torrents.php?id=1&token=secret",
        "/torrents.php?id=1&id=2",
        "/torrents.php?id=1&json=html",
        "https://passthepopcorn.me:444/torrents.php?id=1",
    ],
)
def test_unsafe_or_non_api_redirect_is_rejected(location):
    assert ptp_api_redirect("https://passthepopcorn.me/torrents.php", location) is None


def test_ptp_group_redirect_forces_json_and_paces_second_request(tmp_path):
    requests = []
    clock = [1800000000.0]
    waits = []

    def now():
        return clock[0]

    def sleep(seconds):
        waits.append(seconds)
        clock[0] += seconds

    def handle(request):
        requests.append(request)
        assert request.url.host == "passthepopcorn.me"
        assert request.headers["ApiKey"] == "fixture-key"
        if len(requests) == 1:
            return httpx.Response(302, headers={"Location": "torrents.php?id=123"})
        assert request.url.params["id"] == "123" and request.url.params["json"] == "1"
        assert "imdb" not in request.url.params
        return httpx.Response(200, json={"Page": "Details", "GroupId": "123"})

    limiter = APIPacer(tmp_path / "limits.db", interval=10, clock=now, sleeper=sleep)
    with httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=False) as client:
        data = API(client, interval=0, pacer=limiter).request(
            "GET", "https://passthepopcorn.me/torrents.php", params={"imdb": "1234567", "json": "noredirect"}, headers={"ApiKey": "fixture-key"}
        )
    assert data["GroupId"] == "123" and waits == [10]


def test_second_redirect_and_html_never_prove_absence():
    for response in [httpx.Response(302, headers={"Location": "/torrents.php?id=1"}), httpx.Response(200, text="<html>Login</html>")]:

        def handle(_request, selected=response):
            return selected

        with httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=False) as client, pytest.raises(RunnerError):
            API(client, interval=0).request("GET", "https://passthepopcorn.me/torrents.php")

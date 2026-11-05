# ruff: noqa: S101
"""PTP missing-title search redirects must retain the exact requested IMDb."""

import httpx
import pytest

from src.catalogue_rate import ptp_api_redirect
from src.catalogue_runner import API, Trackers


@pytest.mark.parametrize(
    "target",
    [
        "/torrents.php?searchstr=tt9999999",
        "/torrents.php?searchstr=anything",
        "/torrents.php?searchstr=tt6543194&token=secret",
        "/torrents.php?searchstr=tt6543194&searchstr=tt9999999",
    ],
)
def test_search_scope_cannot_change_or_broaden(target):
    assert ptp_api_redirect("https://passthepopcorn.me/torrents.php?imdb=6543194&json=noredirect", target) is None


def test_same_imdb_search_redirect_uses_explicit_json():
    calls = []

    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(302, headers={"Location": "torrents.php?searchstr=tt6543194"})
        assert request.url.params["searchstr"] == "tt6543194" and request.url.params["json"] == "1"
        assert "imdb" not in request.url.params
        return httpx.Response(200, json={"Page": "Browse", "TotalResults": 0, "Movies": []})

    with httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=False) as client:
        checker = Trackers(API(client, interval=0), {"TRACKERS": {"PASSTHEPOPCORN": {"ApiUser": "fixture", "api_key": "fixture"}}}, ["PTP"])
        assert checker.check_until_hit("tt6543194") == {"PTP": "absent"}
    assert len(calls) == 2

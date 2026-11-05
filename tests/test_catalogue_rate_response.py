# ruff: noqa: S101
"""Some tracker APIs report throttling inside HTTP-200 JSON envelopes."""

from types import SimpleNamespace

import pytest

from src.catalogue_rate import APIPacer, RateLimitError


@pytest.mark.parametrize(
    "body,limited",
    [
        ({"status": 5, "message": "Too many requests"}, True),
        ({"success": False, "error": "Rate limit exceeded"}, True),
        ({"status": 0, "message": "Rate limit information only"}, False),
        ({"status": 2, "message": "Authentication rejected"}, False),
    ],
)
def test_logical_api_throttle_records_shared_cooldown(tmp_path, body, limited):
    def clock():
        return 1800000000.0

    pacer = APIPacer(tmp_path / "limits.db", clock=clock)
    pacer.acquire("hdbits.org")
    response = SimpleNamespace(status_code=200, headers={}, json=lambda: body)
    assert pacer.record_response("hdbits.org", response) == (429 if limited else 200)
    if limited:
        with pytest.raises(RateLimitError):
            pacer.acquire("hdbits.org")

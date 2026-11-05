# ruff: noqa: S101
"""No-network pacing tests across fresh client/subprocess-equivalent instances."""

from pathlib import Path

import pytest

from src.catalogue_rate import APIPacer, RateLimitError


class Clock:
    def __init__(self):
        self.value = 1800000000.0
        self.waits = []

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.value += seconds


def pacer(path: Path, clock, limit=200):
    return APIPacer(path, interval=10, daily_limit=limit, clock=clock.now, sleeper=clock.sleep)


def test_delay_survives_new_client_instance(tmp_path):
    clock = Clock()
    path = tmp_path / "rate.db"
    pacer(path, clock).acquire("hdbits.org")
    pacer(path, clock).acquire("hdbits.org")
    assert clock.waits == [10]
    pacer(path, clock).acquire("aither.cc")
    assert clock.waits == [10]


def test_429_retry_after_persists_without_immediate_retries(tmp_path):
    clock = Clock()
    path = tmp_path / "rate.db"
    first = pacer(path, clock)
    first.acquire("aither.cc")
    first.record("aither.cc", 429, {"Retry-After": "120"})
    with pytest.raises(RateLimitError):
        pacer(path, clock).acquire("aither.cc")
    assert clock.waits == []
    clock.value += 120
    pacer(path, clock).acquire("aither.cc")


def test_daily_budget_persists_and_only_rolls_at_utc_day(tmp_path):
    clock = Clock()
    path = tmp_path / "rate.db"
    pacer(path, clock, 1).acquire("hdbits.org")
    with pytest.raises(RateLimitError):
        pacer(path, clock, 1).acquire("hdbits.org")
    clock.value += 86400
    pacer(path, clock, 1).acquire("hdbits.org")


def test_zero_remaining_uses_server_reset(tmp_path):
    clock = Clock()
    path = tmp_path / "rate.db"
    client = pacer(path, clock)
    client.acquire("passthepopcorn.me")
    client.record("passthepopcorn.me", 200, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(clock.value + 3600)})
    clock.value += 100
    with pytest.raises(RateLimitError):
        pacer(path, clock).acquire("passthepopcorn.me")
    clock.value += 3500
    pacer(path, clock).acquire("passthepopcorn.me")

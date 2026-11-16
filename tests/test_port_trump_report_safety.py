"""Fork safety gates for upstream report plans."""
from unittest.mock import AsyncMock

import pytest

from src.meta import Meta
from src import trump_reports


class Tracker:
    trump_support = trump_reports.TrumpSupport()

    def __init__(self, config):
        pass


def release(status, *, tracker="AITHER", target="42", protected=None):
    meta = Meta(tracker_status={tracker: status})
    meta.trump_plans[tracker] = trump_reports.TrumpPlan(tracker, target, "Old", trump_reports.TRUMPABLE).to_dict()
    if protected is not None:
        meta["LST_protected_ids"] = protected
    return meta


@pytest.mark.asyncio
async def test_report_is_not_submitted_for_failed_or_unknown_upload(monkeypatch):
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(trump_reports, "_send", send)
    for success in (False, None):
        meta = release({"upload": True, "upload_success": success, "torrent_id": "99"})
        assert await trump_reports.submit_reports(meta, {}, {"AITHER": Tracker}) == {}
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_successful_upload_submits_one_report(monkeypatch):
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(trump_reports, "_send", send)
    meta = release({"upload": True, "upload_success": True, "torrent_id": "99"})
    assert await trump_reports.submit_reports(meta, {}, {"AITHER": Tracker}) == {"AITHER": True}
    send.assert_awaited_once()


@pytest.mark.asyncio
async def test_self_and_protected_reports_are_never_submitted(monkeypatch):
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(trump_reports, "_send", send)
    self_report = release({"upload": True, "upload_success": True, "torrent_id": "42"})
    assert await trump_reports.submit_reports(self_report, {}, {"AITHER": Tracker}) == {"AITHER": False}
    protected = release({"upload": True, "upload_success": True, "torrent_id": "99"}, tracker="LST", protected=[42])
    assert await trump_reports.submit_reports(protected, {}, {"LST": Tracker}) == {}
    send.assert_not_awaited()

"""PTP bandwidth waits must re-evaluate policy before form submission."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src import trackerhandle
from src.meta import Meta
from src.slot_rules.models import SlotDecision, Verdict


@pytest.mark.asyncio
@pytest.mark.parametrize('verdict', [Verdict.ALLOW, Verdict.BLOCK, Verdict.REVIEW, 'search_failure'])
async def test_ptp_bandwidth_refresh_cannot_bypass_policy(monkeypatch, verdict):
    name='PASSTHEPOPCORN'
    fake=SimpleNamespace(tracker=name, get_group_by_imdb=AsyncMock(return_value='123'), search_existing=AsyncMock(return_value=[{'name':'new release','size':123}]), fill_upload_form=AsyncMock(return_value=('unused',{})), upload=AsyncMock(return_value=True))
    if verdict=='search_failure':
        fake.search_existing.side_effect=ValueError('synthetic API failure')
    monkeypatch.setattr(trackerhandle,'PassThePopcorn',lambda **kwargs:fake)
    monkeypatch.setattr(trackerhandle,'TrackerSetup',lambda **kwargs:SimpleNamespace(trackers_enabled=lambda meta:[name]))
    monkeypatch.setattr(trackerhandle,'Wait',lambda config:SimpleNamespace(wait_for_bandwidth=AsyncMock(return_value=True)))
    monkeypatch.setattr(trackerhandle,'provision_tracker_torrents',AsyncMock())
    monkeypatch.setattr(trackerhandle,'check_tracker_image_hosts',AsyncMock())
    monkeypatch.setattr(trackerhandle,'record_event_async',AsyncMock())
    decision=SlotDecision(verdict=verdict if verdict!='search_failure' else Verdict.REVIEW,reason='policy recheck',tracker=name,rules_date=date(2026,10,19))
    monkeypatch.setattr(trackerhandle,'evaluate_slots',AsyncMock(return_value=decision))
    # A permissive basic filter must not make a policy REVIEW disappear.
    monkeypatch.setattr(trackerhandle,'DupeChecker',lambda config:SimpleNamespace(filter_dupes=AsyncMock(return_value=[])))
    meta=Meta(name='Film',category='MOVIE',trackers=[name],tracker_status={name:{'upload':True}},qbit_bandwidth_threshold=1,qbit_bandwidth_time=1,initial_dupes={name:[]})
    client=SimpleNamespace(add_to_client=AsyncMock())
    await trackerhandle.process_trackers(meta,{'DEFAULT':{'smart_image_host_selection':False,'multiScreens':0}},client,[],{},[],[],bandwidth_control=True)
    fake.get_group_by_imdb.assert_awaited_once_with(meta.imdb,strict=True,allow_prompt=False)
    if verdict is Verdict.ALLOW:
        fake.upload.assert_awaited_once()
        client.add_to_client.assert_awaited_once()
    else:
        fake.upload.assert_not_awaited()
        fake.fill_upload_form.assert_not_awaited()
        client.add_to_client.assert_not_awaited()
        assert meta.tracker_status[name]['skipped'] is True

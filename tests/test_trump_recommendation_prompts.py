"""Recommended replacements must reach the existing opt-in report workflow."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from src.meta import Meta
from src.slot_rules.models import SlotDecision, Verdict
from src.slot_rules.profile import profile_from_entry
from src.slot_rules.trackers.aither import AitherSlotRules
from src.slot_rules.trackers.lst import LstSlotRules
from src.trackersetup import TrackerSetup
from src.uphelper import UploadHelper


def recommendation(tracker, **extra):
    return SlotDecision(verdict=Verdict.ALLOW,reason='Replacement recommended',tracker=tracker,rules_date=date(2026,10,15),conflicts=[{'id':42,'name':'Old release'}],trump_recommended=True,**extra)


@pytest.mark.parametrize('rules',[AitherSlotRules,LstSlotRules])
def test_replacement_action_is_explicit_not_inferred_from_message(rules):
    old=profile_from_entry({'name':'Film.2021.1080p.AMZN.WEB-DL.H264-GRP','id':42},provider='AMZN')
    new=profile_from_entry({'name':'Film.2021.REPACK.1080p.AMZN.WEB-DL.H264-GRP'},provider='AMZN')
    result=rules().evaluate(new,[old])
    assert result.verdict is Verdict.ALLOW and result.trump_recommended is True
    assert result.conflicts[0]['id']==42
    assert rules().evaluate(new,[]).trump_recommended is False


@pytest.mark.asyncio
@pytest.mark.parametrize('tracker',['AITHER','LST'])
@pytest.mark.parametrize('filtered_empty',[True,False])
async def test_rule_replacement_offers_report_without_server_flag(monkeypatch,tracker,filtered_empty):
    helper=UploadHelper({'DEFAULT':{}})
    prompt=AsyncMock(return_value=True)
    monkeypatch.setattr(helper,'prompt_yes_no',prompt)
    meta=Meta(unattended=False)
    result,meta=await helper.dupe_check([] if filtered_empty else [{'name':'Old release','id':42}],meta,tracker,recommendation(tracker))
    assert result is False and meta.were_trumping is True
    assert meta[tracker+'_trumpable_id']==42
    assert 'creating a report' in prompt.await_args.args[0]
    assert prompt.await_args.kwargs['default'] is False


@pytest.mark.asyncio
async def test_declining_report_does_not_record_trump_intent(monkeypatch):
    helper=UploadHelper({'DEFAULT':{}})
    monkeypatch.setattr(helper,'prompt_yes_no',AsyncMock(side_effect=[False,True]))
    rejected,meta=await helper.dupe_check([],Meta(unattended=False),'AITHER',recommendation('AITHER'))
    assert rejected is False and meta.were_trumping is False
    assert not meta.get('AITHER_trumpable_id')


@pytest.mark.asyncio
async def test_unattended_recommendation_does_not_approve_report(monkeypatch):
    helper=UploadHelper({'DEFAULT':{}})
    prompt=AsyncMock(side_effect=AssertionError('unattended must not prompt'))
    monkeypatch.setattr(helper,'prompt_yes_no',prompt)
    _,meta=await helper.dupe_check([],Meta(unattended=True),'AITHER',recommendation('AITHER'))
    assert meta.were_trumping is False
    prompt.assert_not_awaited()


@pytest.mark.asyncio
async def test_nonreplacement_only_offers_explicit_manual_report(monkeypatch):
    helper=UploadHelper({'DEFAULT':{}})
    prompt=AsyncMock(side_effect=[False,True])
    monkeypatch.setattr(helper,'prompt_yes_no',prompt)
    decision=recommendation('AITHER');decision.trump_recommended=False
    _,meta=await helper.dupe_check([],Meta(unattended=False),'AITHER',decision)
    assert meta.were_trumping is False
    assert 'manual trump report' in prompt.await_args_list[0].args[0]
    assert prompt.await_args_list[0].kwargs['default'] is False
    assert prompt.await_args_list[1].kwargs['default'] is True


@pytest.mark.asyncio
async def test_filtered_server_marked_trump_retains_prompt(monkeypatch):
    helper=UploadHelper({'DEFAULT':{}})
    monkeypatch.setattr(helper,'prompt_yes_no',AsyncMock(return_value=True))
    decision=recommendation('AITHER');decision.trump_recommended=False;decision.verdict=Verdict.BLOCK
    decision.conflicts[0]['trumpable']=True
    _,meta=await helper.dupe_check([],Meta(unattended=False),'AITHER',decision)
    assert meta.were_trumping is True and meta['AITHER_trumpable_id']==42


@pytest.mark.asyncio
async def test_multiple_replacements_require_target_selection(monkeypatch):
    helper=UploadHelper({'DEFAULT':{}})
    decision=recommendation('AITHER');decision.conflicts.append({'id':43,'name':'Other release'})
    choose=AsyncMock(return_value='43: Other release')
    monkeypatch.setattr('src.uphelper.prompt_in_thread',choose)
    monkeypatch.setattr(helper,'prompt_yes_no',AsyncMock(return_value=True))
    _,meta=await helper.dupe_check([],Meta(unattended=False),'AITHER',decision)
    assert meta['AITHER_trumpable_id']==43
    choose.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('success,approved',[(False,True),(None,True),(True,False)])
async def test_no_report_without_successful_approved_upload(monkeypatch,success,approved):
    setup=TrackerSetup({'TRACKERS':{}})
    create=AsyncMock(side_effect=AssertionError('must not reach report endpoint'))
    monkeypatch.setattr(setup,'_create_tracker_instance',create)
    meta=Meta(tracker_status={'AITHER':{'upload_success':success,'torrent_id':'99'}})
    meta['AITHER_were_trumping']=approved
    assert await setup.make_trumpable_report(meta,'AITHER') is False
    create.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('tracker',['AITHER','LST'])
async def test_successful_report_uses_confirmed_target_and_new_torrent(monkeypatch,tracker):
    setup=TrackerSetup({'TRACKERS':{tracker:{'api_key':'synthetic'}}})
    monkeypatch.setattr(setup,'_create_tracker_instance',lambda t:SimpleNamespace(trumping_url='https://example.org/api/trumping-reports/filter' if t=='AITHER' else 'https://example.org/api/reports/torrents/'))
    monkeypatch.setattr('src.trackersetup.cli_ui.ask_string',lambda *a,**kw:'Replacement evidence')
    original=httpx.AsyncClient;posts=[]
    def handler(request):
        import json
        posts.append((str(request.url),json.loads(request.content)))
        return httpx.Response(201,json={'success':True},request=request)
    def client(*args,**kwargs):
        kwargs['transport']=httpx.MockTransport(handler)
        return original(*args,**kwargs)
    monkeypatch.setattr('src.trackersetup.httpx.AsyncClient',client)
    monkeypatch.setattr('src.trackersetup.observe_tracker_response',lambda *a,**kw:None)
    meta=Meta(tracker_status={tracker:{'upload_success':True,'torrent_id':'99'}})
    meta[tracker+'_reported_torrent_id']='42';meta[tracker+'_were_trumping']=True
    assert await setup.make_trumpable_report(meta,tracker) is True
    assert len(posts)==1
    if tracker=='AITHER':
        assert posts[0][1]['reported_torrent_id']=='42' and posts[0][1]['trumping_torrent_id']=='99'
    else:
        assert posts[0][0].endswith('/42/trump') and '/torrents/99' in posts[0][1]['message']


@pytest.mark.asyncio
@pytest.mark.parametrize('tracker',['AITHER','LST'])
async def test_unfiltered_search_keeps_manual_option_when_slot_rules_disabled(monkeypatch,tracker):
    helper=UploadHelper({'DEFAULT':{}})
    prompt=AsyncMock(return_value=True)
    monkeypatch.setattr(helper,'prompt_yes_no',prompt)
    meta=Meta(unattended=False)
    meta[tracker+'_report_candidates']=[{'id':42,'name':'Old release','trumpable':False}]
    rejected,meta=await helper.dupe_check([],meta,tracker,None)
    assert rejected is False and meta.were_trumping is True
    assert meta[tracker+'_trumpable_id']==42
    assert 'manual trump report' in prompt.await_args.args[0]
    assert prompt.await_args.kwargs['default'] is False


@pytest.mark.asyncio
async def test_self_trump_report_never_posts(monkeypatch):
    setup=TrackerSetup({'TRACKERS':{'AITHER':{'api_key':'synthetic'}}})
    monkeypatch.setattr(setup,'_create_tracker_instance',lambda t:SimpleNamespace(trumping_url='https://example.org/filter'))
    client=AsyncMock(side_effect=AssertionError('must not post a self-report'))
    monkeypatch.setattr('src.trackersetup.httpx.AsyncClient',client)
    meta=Meta(tracker_status={'AITHER':{'upload_success':True,'torrent_id':'42'}})
    meta['AITHER_reported_torrent_id']='42';meta['AITHER_were_trumping']=True
    assert await setup.make_trumpable_report(meta,'AITHER') is False
    client.assert_not_called()


@pytest.mark.asyncio
async def test_failed_new_upload_clears_stale_report_success(monkeypatch):
    from src import trackerhandle
    fake=SimpleNamespace(tracker='AITHER',upload=AsyncMock(side_effect=RuntimeError('synthetic upload failure')))
    monkeypatch.setattr(trackerhandle,'TrackerSetup',lambda **kwargs:SimpleNamespace(trackers_enabled=lambda meta:['AITHER']))
    monkeypatch.setattr(trackerhandle,'provision_tracker_torrents',AsyncMock())
    monkeypatch.setattr(trackerhandle,'check_tracker_image_hosts',AsyncMock())
    monkeypatch.setattr(trackerhandle,'record_event_async',AsyncMock())
    client=SimpleNamespace(add_to_client=AsyncMock())
    meta=Meta(name='Film',category='MOVIE',tracker_status={'AITHER':{'upload':True,'upload_success':True,'torrent_id':'old'}})
    await trackerhandle.process_trackers(meta,{'DEFAULT':{'smart_image_host_selection':False}},client,['AITHER'],{'AITHER':lambda **kwargs:fake},[],[],bandwidth_control=False)
    assert meta.tracker_status['AITHER']['upload_success'] is not True
    client.add_to_client.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('tracker',['AITHER','LST'])
async def test_separate_sdr_slot_never_offers_hdr_trump(monkeypatch,tracker):
    helper=UploadHelper({'DEFAULT':{}})
    prompt=AsyncMock(side_effect=AssertionError('separate slot is not a replacement'))
    monkeypatch.setattr(helper,'prompt_yes_no',prompt)
    meta=Meta(unattended=False)
    meta[tracker+'_report_candidates']=[{'id':497065,'name':'The Expendables 3 2014 2160p MA WEB-DL DV HDR H265-GRP'}]
    decision=recommendation(tracker);decision.conflicts=[];decision.trump_recommended=False
    rejected,meta=await helper.dupe_check([],meta,tracker,decision)
    assert rejected is False and meta.were_trumping is False
    prompt.assert_not_awaited()

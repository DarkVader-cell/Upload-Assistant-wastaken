"""Operator-supplied PTP rules: no filesize-derived quality or silent exceptions."""
from dataclasses import replace
from datetime import date
from unittest.mock import AsyncMock

import httpx
import pytest

from src.meta import Meta
from src.slot_rules.models import SlotDecision, Verdict
from src.slot_rules.profile import profile_from_entry
from src.slot_rules.registry import evaluate_slots
from src.slot_rules.trackers.passthepopcorn import PassThePopcornSlotRules, ptp_entry
from src.trackers.GAZELLE.passthepopcorn import PassThePopcorn
from src.uphelper import UploadHelper

ALLOW, BLOCK, REVIEW = Verdict.ALLOW, Verdict.BLOCK, Verdict.REVIEW


def p(name, **entry):
    return profile_from_entry({'name': 'Film.2020.' + name, **entry})


def decide(upload, *existing, meta=None):
    return PassThePopcornSlotRules(meta).evaluate(upload, existing)


@pytest.mark.parametrize('name', ['720p.BluRay.x264-A', '1080p.BluRay.x264-A', '2160p.BluRay.x265-A', '2160p.BluRay.HDR10.x265-A', '2160p.WEB-DL.HDR10.H265-A', '1080p.BluRay.HDR10.x265-A'])
def test_vacant_slots(name):
    assert decide(p(name)).verdict is ALLOW


@pytest.mark.parametrize('gap', [0.01, 0.19, 0.20, 0.40, 0.90])
def test_size_differences_never_prove_quality_or_allow_second_encode(gap):
    a = p('1080p.BluRay.x264-A', size=10**10)
    b = p('1080p.BluRay.x264-B', size=int(10**10 * (1-gap)))
    assert decide(a, b).verdict is REVIEW


@pytest.mark.parametrize('dynamic', ['HDR10', 'DV.HDR10', 'HDR10Plus'])
def test_hdr_web_blocked_once_bluray_hdr_encode_exists(dynamic):
    a = p('2160p.WEB-DL.'+dynamic+'.H265-A')
    b = p('2160p.BluRay.HDR10.x265-B', Source='Blu-ray')
    assert decide(a, b).verdict is BLOCK


def test_unknown_codec_does_not_bypass_hdr_web_prohibition():
    assert decide(p('2160p.WEB-DL.HDR10-A'), p('2160p.BluRay.HDR10.x265-B')).verdict is BLOCK


def test_hdr_web_prohibition_is_cut_specific():
    assert decide(p('Extended.2160p.WEB-DL.HDR10.H265-A'), p('2160p.BluRay.HDR10.x265-B')).verdict is ALLOW


def test_sdr_is_not_hdr_and_has_its_own_uhd_slots():
    assert decide(p('2160p.WEB-DL.H265-A'), p('2160p.BluRay.HDR10.x265-B')).verdict is ALLOW
    assert decide(p('2160p.BluRay.x264-A'), p('2160p.BluRay.HDR10.x265-B')).verdict is ALLOW


def test_compatible_dv_does_not_create_an_extra_hdr10_encode_slot():
    a = p('2160p.BluRay.DV.HDR10.x265-A')
    b = p('2160p.BluRay.HDR10.x265-B')
    assert decide(a, b).verdict is REVIEW
    assert decide(a, b, replace(b, name='other')).verdict is REVIEW


def test_dv_profile5_separate_without_hdr10():
    a = p('2160p.BluRay.DV.x265-A', RemasterTitle='DV Profile 5')
    b = p('2160p.BluRay.HDR10.x265-B')
    assert decide(a, b).verdict is ALLOW


def test_bare_dv_label_does_not_imply_profile5():
    assert decide(p('2160p.BluRay.DV.x265-A')).verdict is REVIEW
    assert decide(p('2160p.WEB-DL.DV.H265-A')).verdict is REVIEW


def test_profile5_with_hdr10_is_conflicting_evidence():
    assert decide(p('2160p.BluRay.DV.HDR10.x265-A', RemasterTitle='DV Profile 5')).verdict is REVIEW


@pytest.mark.parametrize('dynamic', ['HLG', 'PQ10'])
def test_non_hdr10_dynamic_range_needs_review(dynamic):
    assert decide(p('2160p.BluRay.'+dynamic+'.x265-A')).verdict is REVIEW


def test_sdr_web_1080_hevc_always_needs_avc_comparisons():
    assert decide(p('1080p.WEB-DL.H265-A')).verdict is REVIEW


def test_web_provider_does_not_create_a_slot():
    assert decide(p('1080p.AMZN.WEB-DL.H264-A'), p('1080p.NF.WEB-DL.H264-B')).verdict is REVIEW


def test_distributor_remaster_name_does_not_create_a_cut():
    assert decide(p('Criterion.1080p.BluRay.x264-A'), p('Remastered.1080p.BluRay.x264-B')).verdict is REVIEW


def test_actual_distinct_cut_has_independent_slots():
    assert decide(p('Extended.1080p.BluRay.x264-A'), p('1080p.BluRay.x264-B')).verdict is ALLOW


def test_sd_web_blocked_by_hd_equivalent():
    assert decide(p('480p.WEB-DL.H264-A'), p('1080p.WEB-DL.H264-B')).verdict is BLOCK


def test_open_matte_requires_oar_comparisons():
    assert decide(p('Open.Matte.1080p.BluRay.x264-A')).verdict is REVIEW


def test_unknown_occupant_traits_do_not_mean_vacancy():
    assert decide(p('1080p.BluRay.x264-A'), p('unidentified-B')).verdict is REVIEW


def test_exact_release_blocks():
    a=p('1080p.BluRay.x264-A')
    assert decide(a, replace(a, exact=True)).verdict is BLOCK


@pytest.mark.parametrize('kind,genres,expected', [('movie', [], ALLOW), ('tvSeries', [], BLOCK), ('tvSeries', ['Documentary'], REVIEW), ('tvMiniSeries', [], REVIEW), ('movie', ['Adult'], BLOCK), ('unknown', [], REVIEW)])
def test_content_gates(kind, genres, expected):
    meta=Meta(category='MOVIE', imdb_id='123', imdb_info={'type':kind,'genres':genres}, type='ENCODE', resolution='1080p', video_codec='AVC', container='mkv')
    assert decide(p('1080p.BluRay.x264-A'), meta=meta).verdict is expected


def test_content_review_cannot_mask_hard_hdr_web_block():
    meta=Meta(category='MOVIE', imdb_id='123', type='WEBDL', resolution='2160p', hdr='HDR10', imdb_info={})
    assert decide(p('2160p.WEB-DL.HDR10.H265-A'), p('2160p.BluRay.HDR10.x265-B'), meta=meta).verdict is BLOCK


def test_structured_api_traits_are_preserved():
    raw={'Id':12,'ReleaseName':'Film.2020','Resolution':'2160p','Source':'Blu-ray','Codec':'x265','Container':'mkv','RemasterTitle':'HDR10 Extended','Size':'12345','NotMainMovie':False,'MediaInfo':'report'}
    entry=ptp_entry(raw)
    profile=profile_from_entry(entry)
    assert entry['Source']=='Blu-ray' and entry['NotMainMovie'] is False
    assert entry['media_info']=='report' and profile.kind=='ENCODE'
    assert profile.size==12345


@pytest.mark.asyncio
async def test_registry_retains_hard_block_and_does_not_lookup_provider(monkeypatch):
    meta=Meta(category='MOVIE', imdb_id='123', imdb_info={'type':'movie'}, name='Film.2020.2160p.WEB-DL.HDR10.H265-A', type='WEBDL', resolution='2160p', hdr='HDR10', video_codec='HEVC')
    provider=AsyncMock(side_effect=AssertionError('PTP must not query provider services'))
    monkeypatch.setattr('src.slot_rules.registry._provider',provider)
    entry=ptp_entry({'Id':1,'ReleaseName':'Film.2020.2160p.BluRay.HDR10.x265-B','Source':'Blu-ray','Resolution':'2160p','Codec':'x265','RemasterTitle':'HDR10'})
    result=await evaluate_slots([entry],meta,'PASSTHEPOPCORN',{})
    assert result.verdict is BLOCK
    provider.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_preserves_all_quality_bands(monkeypatch):
    raw=[{'Id':1,'ReleaseName':'Film.2020.480p.WEB-DL.H264-A','Resolution':'480p','Quality':'Standard Definition','Source':'WEB','Codec':'H.264'}, {'Id':2,'ReleaseName':'Film.2020.2160p.BluRay.HDR10.x265-B','Resolution':'2160p','Quality':'Ultra High Definition','Source':'Blu-ray','Codec':'x265','RemasterTitle':'HDR10'}]
    await _api(monkeypatch, {'Torrents':raw})
    meta=Meta(category='MOVIE', resolution='480p', sd=1)
    result=await PassThePopcorn({'TRACKERS':{'PASSTHEPOPCORN':{}}}).search_existing('1',meta)
    assert len(result)==2
    assert meta['PASSTHEPOPCORN_title_releases']==result


async def _api(monkeypatch, data, status=200):
    original=httpx.AsyncClient
    def make(*args, **kwargs):
        kwargs['transport']=httpx.MockTransport(lambda request:httpx.Response(status,json=data,request=request))
        return original(*args,**kwargs)
    monkeypatch.setattr('src.trackers.GAZELLE.passthepopcorn.httpx.AsyncClient',make)
    monkeypatch.setattr('src.trackers.GAZELLE.passthepopcorn.asyncio.sleep',AsyncMock())


@pytest.mark.asyncio
@pytest.mark.parametrize('data', [{}, {'Error':'denied'}, {'Torrents':None}, {'Torrents':[None]}])
async def test_bad_inventory_is_not_an_empty_group(monkeypatch,data):
    await _api(monkeypatch,data)
    with pytest.raises(ValueError):
        await PassThePopcorn({'TRACKERS':{'PASSTHEPOPCORN':{}}}).search_existing('1',Meta())


@pytest.mark.asyncio
@pytest.mark.parametrize('data,status', [({},200), ({'Error':'denied'},403), ({'Page':'Details'},200), ({'TotalResults':1,'Movies':[{}]},200)])
async def test_strict_lookup_rejects_unknown_group_state(monkeypatch,data,status):
    await _api(monkeypatch,data,status)
    with pytest.raises(ValueError):
        await PassThePopcorn({'TRACKERS':{'PASSTHEPOPCORN':{}}}).get_group_by_imdb('123',strict=True)


@pytest.mark.asyncio
async def test_explicit_zero_results_is_valid_absence(monkeypatch):
    await _api(monkeypatch,{'TotalResults':0,'Movies':[]})
    assert await PassThePopcorn({'TRACKERS':{'PASSTHEPOPCORN':{}}}).get_group_by_imdb('123',strict=True) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('verdict,unattended,force', [(BLOCK,False,False),(BLOCK,True,True),(REVIEW,True,False),(REVIEW,True,True)])
async def test_ptp_rejection_is_not_an_overridable_dupe_or_cross_seed(monkeypatch,verdict,unattended,force):
    helper=UploadHelper({'DEFAULT':{}})
    prompt=AsyncMock(return_value=True)
    monkeypatch.setattr(helper,'prompt_yes_no',prompt)
    meta=Meta(unattended=unattended,dupe=force)
    meta['PASSTHEPOPCORN_cross_seed']=True
    decision=SlotDecision(verdict=verdict,reason='policy test',tracker='PASSTHEPOPCORN',rules_date=date(2026,10,19))
    rejected,result=await helper.dupe_check([],meta,'PASSTHEPOPCORN',decision)
    assert rejected is True and result['PASSTHEPOPCORN_cross_seed'] is False
    prompt.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('approved',[True,False])
async def test_attended_review_requires_explicit_evidence_confirmation(monkeypatch,approved):
    helper=UploadHelper({'DEFAULT':{}})
    prompt=AsyncMock(return_value=approved)
    monkeypatch.setattr(helper,'prompt_yes_no',prompt)
    decision=SlotDecision(verdict=REVIEW,reason='staff approval required',tracker='PASSTHEPOPCORN',rules_date=date(2026,10,19))
    rejected,_=await helper.dupe_check([],Meta(unattended=False),'PASSTHEPOPCORN',decision)
    assert rejected is not approved
    assert prompt.await_count==1 and prompt.await_args.kwargs['default'] is False
    assert 'evidence/staff approval' in prompt.await_args.args[0]


def test_blue_in_title_does_not_mean_bluray_source():
    existing=p('Blue.Film.2160p.WEBRip.HDR10.x265-B')
    assert decide(p('2160p.WEB-DL.HDR10.H265-A'),existing).verdict is ALLOW


def test_unknown_source_hdr_encode_requires_review_before_hdr_web():
    assert decide(p('2160p.WEB-DL.HDR10.H265-A'),p('2160p.HDR10.x265-B')).verdict is REVIEW


@pytest.mark.parametrize('kind,imdb', [('tvMiniSeries','123'),('movie',None)])
def test_staff_approval_review_does_not_hide_mp4_ban(kind,imdb):
    meta=Meta(category='MOVIE',imdb_id=imdb,imdb_info={'type':kind},container='mp4')
    assert decide(p('1080p.BluRay.x264-A'),meta=meta).verdict is BLOCK


def test_missing_dynamic_range_label_is_not_proof_of_sdr():
    candidate=p('2160p.WEB-DL.HDR10.H265-A')
    assert decide(candidate,p('2160p.BluRay.x265-B')).verdict is REVIEW
    assert decide(candidate,p('2160p.BluRay.SDR.x265-B')).verdict is ALLOW


def test_web_rip_does_not_bypass_hdr_web_prohibition():
    assert decide(p('2160p.WEBRip.HDR10.x265-A'),p('2160p.BluRay.HDR10.x265-B')).verdict is BLOCK


@pytest.mark.asyncio
@pytest.mark.parametrize('category',['XXX','BOOK','GAME','MUSIC'])
async def test_nonfilm_categories_do_not_bypass_ptp_content_gate(category):
    result=await evaluate_slots([],Meta(category=category),'PASSTHEPOPCORN',{})
    assert result.verdict is BLOCK


@pytest.mark.parametrize('name',['1080p.WEB-DL-A','720p.WEB-DL.H265-A','480p.WEB-DL.XviD-A','1080p.BluRay.HDR10.x264-A'])
def test_unknown_or_nonpreferred_formats_require_review(name):
    assert decide(p(name)).verdict is REVIEW


@pytest.mark.asyncio
async def test_ambiguous_group_does_not_prompt_in_unattended_lookup(monkeypatch):
    await _api(monkeypatch,{'TotalResults':2,'Movies':[{'GroupId':1},{'GroupId':2}]})
    prompt=AsyncMock(side_effect=AssertionError('must not prompt'))
    monkeypatch.setattr('src.trackers.GAZELLE.passthepopcorn.prompt_in_thread',prompt)
    with pytest.raises(ValueError):
        await PassThePopcorn({'TRACKERS':{'PASSTHEPOPCORN':{}}}).get_group_by_imdb('123',strict=True,allow_prompt=False)
    prompt.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('unattended',[True,False])
async def test_vacant_ptp_slot_also_displays_recommendation(monkeypatch,unattended):
    helper=UploadHelper({'DEFAULT':{}})
    shown=[]
    monkeypatch.setattr(helper,'_show_slot_decision',lambda decision,meta:shown.append(decision))
    decision=SlotDecision(verdict=ALLOW,reason='Vacant PTP slot',slot='Encode 1080p',tracker='PASSTHEPOPCORN',rules_date=date(2026,10,19))
    rejected,_=await helper.dupe_check([],Meta(unattended=unattended),'PASSTHEPOPCORN',decision)
    assert rejected is False and shown==[decision]

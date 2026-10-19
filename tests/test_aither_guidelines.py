"""Aither's operator-supplied slot overview and resolution-specific exceptions."""
from dataclasses import replace
from datetime import date
from unittest.mock import AsyncMock

import pytest

from src.meta import Meta
from src.slot_rules.models import SlotDecision, Verdict
from src.slot_rules.profile import profile_from_entry
from src.slot_rules.registry import evaluate_slots
from src.slot_rules.trackers.aither import AitherSlotRules
from src.uphelper import UploadHelper

ALLOW, BLOCK, REVIEW = Verdict.ALLOW, Verdict.BLOCK, Verdict.REVIEW


def p(name, **fields):
    return profile_from_entry({'name':'Film.2020.'+name,**fields},provider='AMZN')


def evaluate(candidate,*existing,meta=None):
    return AitherSlotRules(meta).evaluate(candidate,existing)


@pytest.mark.parametrize('name',[
    '720p.WEB-DL.H264-A','720p.BluRay.x264-A','1080p.WEB-DL.H264-A',
    '1080p.WEB-DL.DV.H265-A','1080p.WEB-DL.HDR10.H265-A',
    '1080p.BluRay.x265-A','1080p.BluRay.HDR10.x265-A','1080p.BluRay.REMUX.AVC-A',
    '2160p.WEB-DL.H265-A','2160p.WEB-DL.DV.H265-A','2160p.WEB-DL.HDR10.H265-A',
    '2160p.WEB-DL.HDR10+.H265-A','2160p.BluRay.x265-A','2160p.BluRay.HDR10.x265-A',
    '2160p.BluRay.REMUX.HEVC-A','2160p.BluRay.HDR10.REMUX.HEVC-A'])
def test_listed_vacant_slots(name):
    assert evaluate(p(name)).verdict is ALLOW


@pytest.mark.parametrize('old,new',[
    ('HDR10','DV.HDR10'),('HDR10+','DV.HDR10+')])
def test_explicit_web_trump_priority(old,new):
    result=evaluate(p('2160p.WEB-DL.'+new+'.H265-A'),p('2160p.WEB-DL.'+old+'.H265-B',id=42))
    assert result.verdict is ALLOW and result.trump_recommended


def test_sdr_dv_hdr_and_hdr10plus_web_slots_are_independent():
    for new,old in [('SDR','DV'),('SDR','HDR10'),('HDR10','HDR10+'),('DV','HDR10')]:
        result=evaluate(p('2160p.WEB-DL.'+new+'.H265-A'),p('2160p.WEB-DL.'+old+'.H265-B',id=42))
        assert result.verdict is ALLOW and not result.conflicts and not result.trump_recommended


def test_hdr10plus_does_not_prove_hybrid_provenance():
    profile=p('2160p.BluRay.HDR10+.x265-A')
    assert 'HYBRID' not in AitherSlotRules().key(profile)
    assert 'HDR' in AitherSlotRules().key(profile)


@pytest.mark.parametrize('name', ['1080p.BluRay.Hybrid.HDR10+.x265-A','2160p.BluRay.Hybrid.DV.HDR10.x265-A','2160p.BluRay.Hybrid.DV.HDR10+.REMUX.HEVC-A'])
def test_hybrids_need_grades_and_plots_even_when_vacant(name):
    result=evaluate(p(name))
    assert result.verdict is REVIEW and result.requires_evidence
    assert 'grade' in result.reason.lower() and 'plot' in result.reason.lower()


def test_hybrid_quality_exception_prevents_automatic_retail_dv_trump():
    new=p('2160p.BluRay.DV.HDR10.x265-A')
    old=p('2160p.BluRay.Hybrid.DV.HDR10+.x265-B',id=42)
    result=evaluate(new,old)
    assert result.verdict is REVIEW and result.requires_evidence and not result.trump_recommended


def test_hybrid_occupied_slot_is_a_real_report_candidate_after_evidence():
    result=evaluate(p('2160p.BluRay.Hybrid.DV.HDR10+.x265-A'),p('2160p.BluRay.Hybrid.HDR10+.x265-B',id=42))
    assert result.verdict is REVIEW and result.conflicts[0]['id']==42


@pytest.mark.parametrize('name',['1080p.WEBRip.x264-A','1080p.WEBRip.x265-A','720p.WEBRip.x264-A'])
def test_webrips_require_ten_comparison_screenshots(name):
    result=evaluate(p(name))
    assert result.verdict is REVIEW and result.requires_evidence
    assert '10 comparison screenshots' in result.reason
    assert '6 comparison' not in result.why
    assert 'Blu-ray' in result.why and 'Encode' in result.why


def test_relabelled_web_encode_still_requires_source_comparisons():
    meta=Meta(source='WEB')
    result=evaluate(p('1080p.x264-A',type='ENCODE'),meta=meta)
    assert result.verdict is REVIEW and result.requires_evidence


def test_downscaled_webrip_competes_with_encode_not_direct_web():
    rules=AitherSlotRules()
    assert rules.key(p('1080p.WEBRip.x264-A'))==rules.key(p('1080p.BluRay.x264-B'))
    assert rules.key(p('1080p.WEBRip.x264-A'))!=rules.key(p('1080p.WEB-DL.H264-B'))


def test_three_d_has_its_own_slot():
    assert evaluate(p('1080p.3D.BluRay.x264-A'),p('1080p.BluRay.x264-B')).verdict is ALLOW


def test_alternate_cut_requires_documented_differences_not_report_target():
    result=evaluate(p('Extended.1080p.BluRay.x264-A'),p('1080p.BluRay.x264-B',id=42))
    assert result.verdict is REVIEW and result.requires_evidence
    assert not result.conflicts


def test_distributor_label_does_not_manufacture_a_slot():
    assert evaluate(p('Criterion.1080p.BluRay.x264-A',size=10**10),p('1080p.BluRay.x264-B',size=10**10)).verdict is BLOCK


def test_open_matte_needs_staff_approval_even_when_vacant():
    result=evaluate(p('Open.Matte.1080p.BluRay.x264-A'))
    assert result.verdict is REVIEW and result.requires_evidence
    assert 'staff approval' in result.reason


def test_oar_separate_slot_requires_staff_approval_not_a_trump():
    result=evaluate(p('1080p.BluRay.x264-A'),p('Open.Matte.1080p.BluRay.x264-B'))
    assert result.verdict is REVIEW and result.requires_evidence and not result.conflicts


@pytest.mark.parametrize('size',[8*10**9,5*10**9,None])
def test_size_alone_cannot_prove_quality_retention_role(size):
    result=evaluate(p('1080p.BluRay.x264-A',size=10**10),p('1080p.BluRay.x264-B',size=size))
    assert result.verdict is REVIEW and result.requires_evidence


def test_less_than_twenty_percent_competes_for_the_same_slot():
    assert evaluate(p('1080p.BluRay.x264-A',size=10**10),p('1080p.BluRay.x264-B',size=95*10**8)).verdict is BLOCK


def test_no_third_quality_retention_slot():
    assert evaluate(p('1080p.BluRay.x264-A',size=10**10),p('1080p.BluRay.x264-B',size=2*10**10),p('1080p.BluRay.x264-C',size=4*10**10)).verdict is BLOCK


def test_internal_does_not_automatically_trump_or_grant_quality():
    result=evaluate(replace(p('1080p.WEB-DL.H264-A'),internal=True),p('1080p.WEB-DL.H264-B'))
    assert result.verdict is REVIEW and result.requires_evidence and not result.trump_recommended


def test_noninternal_accessibility_additional_slot_is_not_allowed():
    assert evaluate(p('1080p.WEB-DL.H264-A',accessibility=['ASL'])).verdict is BLOCK


def test_internal_accessibility_needs_positive_feature_evidence():
    result=evaluate(replace(p('1080p.WEB-DL.H264-A',accessibility=['AD']),internal=True))
    assert result.verdict is REVIEW and result.requires_evidence


def test_ad_in_film_title_does_not_claim_accessibility():
    assert evaluate(p('Ad.Astra.1080p.WEB-DL.H264-A')).verdict is ALLOW


def test_sd_eligibility_is_not_inferred_from_empty_search():
    result=evaluate(p('480p.WEB-DL.H264-A'))
    assert result.verdict is REVIEW and result.requires_evidence
    result=evaluate(p('480p.WEB-DL.H264-A'),p('1080p.WEB-DL.H264-B',id=42))
    assert result.verdict is BLOCK and not result.conflicts


def test_full_disc_hd_source_also_precludes_sd():
    hd=p('1080p.COMPLETE.BLURAY.BD50-A',type='Full Disc')
    assert evaluate(p('480p.WEB-DL.H264-B'),hd).verdict is BLOCK


def test_1440p_needs_absence_of_2160p_source():
    assert evaluate(p('1440p.WEB-DL.H264-A')).verdict is REVIEW
    result=evaluate(p('1440p.WEB-DL.H264-A'),p('2160p.WEB-DL.H265-B',id=42))
    assert result.verdict is BLOCK and not result.conflicts


@pytest.mark.parametrize('name',['480p.DVD5','576p.DVD9','1080p.BluRay.BD50','2160p.BluRay.BD100'])
def test_listed_full_disc_slots_are_available(name):
    assert evaluate(p(name,type='Full Disc')).verdict is ALLOW


def test_full_disc_coexistence_requires_content_or_region_differences():
    result=evaluate(p('1080p.BluRay.BD50-A',type='Full Disc'),p('1080p.BluRay.BD50-B',type='Full Disc',id=42))
    assert result.verdict is REVIEW and result.requires_evidence and not result.conflicts


@pytest.mark.asyncio
@pytest.mark.parametrize('internal,groups,expected',[(True,['GRP'],REVIEW),(False,['GRP'],BLOCK),(True,['OTHER'],BLOCK),(True,[''],BLOCK)])
async def test_registry_uses_configured_internal_group_not_name_claim(internal,groups,expected):
    meta=Meta(category='MOVIE',tag='-GRP',name='Film.1080p.WEB-DL.H264-GRP',type='WEBDL',resolution='1080p',video_codec='AVC')
    meta['AITHER_accessibility']=['AD']
    config={'TRACKERS':{'AITHER':{'internal':internal,'internal_groups':groups}}}
    assert (await evaluate_slots([],meta,'AITHER',config)).verdict is expected


@pytest.mark.asyncio
async def test_registry_full_discs_are_no_longer_basic_fallback():
    meta=Meta(category='MOVIE',is_disc='BDMV',type='DISC',disctype='BD50',resolution='1080p')
    result=await evaluate_slots([],meta,'AITHER',{})
    assert result.verdict is ALLOW


@pytest.mark.asyncio
@pytest.mark.parametrize('unattended,approve,skip',[(True,False,True),(False,False,True),(False,True,False)])
async def test_required_evidence_gates_vacant_slots(monkeypatch,unattended,approve,skip):
    helper=UploadHelper({'DEFAULT':{}})
    prompt=AsyncMock(return_value=approve)
    monkeypatch.setattr(helper,'prompt_yes_no',prompt)
    decision=SlotDecision(verdict=REVIEW,reason='staff approval required',tracker='AITHER',rules_date=date(2026,10,19),requires_evidence=True)
    rejected,meta=await helper.dupe_check([],Meta(unattended=unattended),'AITHER',decision)
    assert rejected is skip
    if unattended:prompt.assert_not_awaited()
    else:assert prompt.await_args.kwargs['default'] is False
    if skip:assert meta['AITHER_cross_seed'] is False


def test_1080p_remux_has_one_slot_not_one_per_codec():
    assert evaluate(p('1080p.BluRay.REMUX.HEVC-A'),p('1080p.BluRay.REMUX.AVC-B')).verdict is BLOCK


def test_loss_of_hdr10plus_is_not_an_automatic_dv_trump():
    result=evaluate(p('1080p.WEB-DL.DV.HDR10.H265-A'),p('1080p.WEB-DL.HDR10+.H265-B'))
    assert result.verdict is REVIEW and result.requires_evidence and not result.trump_recommended


@pytest.mark.asyncio
async def test_bandwidth_refresh_cannot_lose_aither_evidence_gate(monkeypatch):
    from types import SimpleNamespace

    from src import trackerhandle
    fake=SimpleNamespace(tracker='AITHER',search_existing=AsyncMock(return_value=[{'name':'new release','id':42}]),upload=AsyncMock(return_value=True))
    monkeypatch.setattr(trackerhandle,'TrackerSetup',lambda **kwargs:SimpleNamespace(trackers_enabled=lambda meta:['AITHER']))
    monkeypatch.setattr(trackerhandle,'Wait',lambda config:SimpleNamespace(wait_for_bandwidth=AsyncMock(return_value=True)))
    monkeypatch.setattr(trackerhandle,'provision_tracker_torrents',AsyncMock())
    monkeypatch.setattr(trackerhandle,'check_tracker_image_hosts',AsyncMock())
    monkeypatch.setattr(trackerhandle,'record_event_async',AsyncMock())
    decision=SlotDecision(verdict=REVIEW,reason='source evidence changed',tracker='AITHER',rules_date=date(2026,10,19),requires_evidence=True)
    monkeypatch.setattr(trackerhandle,'evaluate_slots',AsyncMock(return_value=decision))
    monkeypatch.setattr(trackerhandle,'DupeChecker',lambda config:SimpleNamespace(filter_dupes=AsyncMock(return_value=[])))
    meta=Meta(name='Film',category='MOVIE',initial_dupes={'AITHER':[]},tracker_status={'AITHER':{'upload':True}},qbit_bandwidth_threshold=1,qbit_bandwidth_time=1)
    client=SimpleNamespace(add_to_client=AsyncMock())
    await trackerhandle.process_trackers(meta,{'DEFAULT':{'smart_image_host_selection':False}},client,['AITHER'],{'AITHER':lambda **kwargs:fake},[],[],bandwidth_control=True)
    fake.upload.assert_not_awaited()
    client.add_to_client.assert_not_awaited()


@pytest.mark.asyncio
async def test_season_pack_review_preserves_webrip_evidence_requirements():
    meta=Meta(category='TV',name='Fictional.Show.S01E01.1080p.AMZN.WEBRip.x264-NEW',type='WEBRIP',resolution='1080p',video_codec='AVC',season='S01',episode='E01',tv_pack=0,service='AMZN')
    pack={'name':'Fictional.Show.S01.1080p.AMZN.WEB-DL.H264-OLD','id':42}
    result=await evaluate_slots([pack],meta,'AITHER',{})
    assert result.verdict is REVIEW and result.requires_evidence
    assert '10 comparison screenshots' in ' '.join([result.reason,*result.notes])

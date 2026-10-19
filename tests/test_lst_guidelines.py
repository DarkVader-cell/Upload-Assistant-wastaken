"""LST supplied guidelines: slot independence, evidence, and permanent protection."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.meta import Meta
from src.slot_rules.models import Verdict
from src.slot_rules.profile import profile_from_entry
from src.slot_rules.registry import evaluate_slots
from src.slot_rules.trackers.lst import LstSlotRules
from src.trackersetup import TrackerSetup
from src.uphelper import UploadHelper

ALLOW, BLOCK, REVIEW = Verdict.ALLOW, Verdict.BLOCK, Verdict.REVIEW


def p(name, provider='AMZN', **fields):
    return profile_from_entry({'name':'Film.2020.'+name,**fields},provider=provider)


def decide(new,*old,meta=None):
    return LstSlotRules(meta).evaluate(new,old)


def meta(**kw):
    return Meta(category='MOVIE',container='mkv',source='BluRay',**kw)


@pytest.mark.parametrize('name', ['1080p.WEB-DL.H264-A','1080p.WEB-DL.H265-A','1080p.WEB-DL.AV1-A','1080p.WEB-DL.DV.H265-A','2160p.WEB-DL.H264-A','2160p.WEB-DL.H265-A','2160p.WEB-DL.AV1-A','2160p.BluRay.AV1-A','1080p.BluRay.HDR10.AV1-A'])
def test_listed_vacant_slots(name):
    assert decide(p(name)).verdict is ALLOW


def test_provider_and_av1_encode_independence():
    assert decide(p('1080p.WEB-DL.H264-A'),p('1080p.WEB-DL.H264-B',provider='DSNP')).verdict is ALLOW
    assert decide(p('2160p.BluRay.AV1-A'),p('2160p.BluRay.x265-B')).verdict is ALLOW


def test_hdr10plus_and_dv_slots_not_sdr_occupants():
    for dynamic in ['DV','HDR10','HDR10+']:
        result=decide(p('2160p.WEB-DL.H265-A'),p('2160p.WEB-DL.'+dynamic+'.H265-B'))
        assert result.verdict is ALLOW and not result.conflicts


@pytest.mark.parametrize('group,internal', [('B',False),('A',False),('B',True)])
def test_other_group_or_noninternal_can_only_coexist_with_internal(group,internal):
    new=replace(p('1080p.REPACK.WEB-DL.H264-'+group),internal=internal)
    old=p('1080p.WEB-DL.H264-A',id=42,internal=True,trumpable=True)
    result=decide(new,old)
    assert result.verdict is REVIEW and result.protected_ids==['42']
    assert not result.trump_recommended


def test_same_internal_group_confirmed_repack_can_replace_same_slot():
    new=replace(p('1080p.REPACK.WEB-DL.H264-A'),internal=True)
    old=p('1080p.WEB-DL.H264-A',id=42,internal=True)
    result=decide(new,old)
    assert result.verdict is ALLOW and result.trump_recommended and result.protected_ids==[]


def test_same_group_different_slot_does_not_authorize_trump():
    new=replace(p('2160p.WEB-DL.H265-A'),internal=True)
    result=decide(new,p('1080p.WEB-DL.H264-A',id=42,internal=True))
    assert result.verdict is ALLOW and result.protected_ids==['42']


def test_webrip_and_webdl_do_not_trump_each_other():
    web=p('1080p.WEB-DL.H264-A',id=42)
    rip=p('1080p.WEBRip.x264-B',id=43)
    result=decide(rip,web)
    assert result.verdict is REVIEW and result.requires_evidence and not result.conflicts
    assert decide(web,rip).verdict is ALLOW


def test_ordinary_provider_lossless_slot_not_global_extra():
    new=replace(p('2160p.WEB-DL.H265-A',provider='DSNP'),audio_lossless=True)
    old=replace(p('2160p.WEB-DL.H265-B'),audio_lossless=True)
    assert decide(new,old).verdict is ALLOW


@pytest.mark.parametrize('codec',['x265','AV1'])
def test_720_encode_codec_is_a_must_not_just_recommendation(codec):
    result=decide(p('720p.BluRay.'+codec+'-A'))
    assert result.verdict is BLOCK and result.constraint_violation


@pytest.mark.parametrize('source',['CAM','DDC','DCP','R5','BOOTLEG'])
def test_preretail_prohibited(source):
    m=Meta(category='MOVIE',container='mkv',source=source)
    assert decide(p('1080p.WEB-DL.H264-A'),meta=m).verdict is BLOCK


@pytest.mark.parametrize('flag',['ai_generated','ai_enhanced','ai_upscaled','ai_dv_hdr_layers','ai_subtitles','LST_invalid_hybrid','illegal_content','malware_release'])
def test_known_prohibited_modifications(flag):
    m=meta();m[flag]=True
    assert decide(p('1080p.WEB-DL.H264-A'),meta=m).verdict is BLOCK


def test_retail_studio_ai_is_an_exception_not_automatic_approval():
    m=meta();m['ai_upscaled']=True;m['LST_studio_ai_retail']=True
    result=decide(p('1080p.WEB-DL.H264-A'),meta=m)
    assert result.verdict is REVIEW and result.requires_evidence


def test_public_web_and_access_wall_exception():
    m=meta();m['publicly_available']=True
    assert decide(p('1080p.WEB-DL.H264-A'),meta=m).verdict is BLOCK
    m['geolocked']=True
    assert decide(p('1080p.WEB-DL.H264-A'),meta=m).verdict is REVIEW


def test_finished_season_requires_pack():
    m=Meta(category='TV',container='mkv',tv_pack=0);m['season_completed']=True
    assert decide(p('1080p.WEB-DL.H264-A'),meta=m).verdict is BLOCK


def test_wrong_container_and_nonmkv_queue_requirement():
    m=Meta(category='MOVIE',container='mp4')
    assert decide(p('1080p.WEB-DL.H264-A'),meta=m).verdict is BLOCK
    m.mediainfo={'media':{'track':[{'@type':'Video','HDR_Format_Profile':'dvhe.05.06'}]}}
    assert decide(p('1080p.WEB-DL.DV.H265-A'),meta=m).verdict is BLOCK
    m.modq=True
    assert decide(p('1080p.WEB-DL.DV.H265-A'),meta=m).verdict is REVIEW


def test_three_d_full_disc_iso_exception():
    m=Meta(category='MOVIE',path='/tmp/disc.iso',container='iso')
    assert decide(p('1080p.COMPLETE.BluRay',type='DISC'),meta=m).verdict is BLOCK
    assert decide(p('1080p.3D.COMPLETE.BluRay',type='DISC'),meta=m).verdict is REVIEW


def test_custom_disc_cannot_follow_unmodified_same_disc():
    m=meta();m['LST_custom_disc']=True;m['LST_unmodified_same_disc_exists']=True
    assert decide(p('1080p.COMPLETE.BluRay',type='DISC'),meta=m).verdict is BLOCK


def test_hybrid_web_provenance_is_not_assumed_from_name():
    result=decide(p('2160p.HYBRID.BluRay.REMUX.DV.HDR10.HEVC-A'))
    assert result.verdict is REVIEW and result.requires_evidence


def audio_meta(fmt='FLAC',channels='6',bits='24',anime=False,title='Main'):
    return meta(anime=anime,mediainfo={'media':{'track':[{'@type':'Audio','Format':fmt,'Channels':channels,'BitDepth':bits,'Title':title,'Default':'Yes'}]}})


@pytest.mark.parametrize('fmt,channels,bits,anime,title', [('FLAC','6','24',True,'Main'),('FLAC','6','16',False,'Main'),('TrueHD','6','24',False,'Main'),('FLAC','2','16',True,'Commentary'),('DTS-HD Master Audio','2','16',False,'Main')])
def test_required_audio_tier_violations(fmt,channels,bits,anime,title):
    result=decide(p('1080p.BluRay.x264-A'),meta=audio_meta(fmt,channels,bits,anime,title))
    assert result.verdict is BLOCK and result.constraint_violation


def test_anime_flac16_51_is_not_rejected_for_channel_layout():
    assert decide(p('1080p.BluRay.x264-A'),meta=audio_meta(bits='16',anime=True)).verdict is REVIEW


@pytest.mark.asyncio
async def test_protected_internal_never_reaches_report_post(monkeypatch):
    setup=TrackerSetup({'TRACKERS':{'LST':{'api_key':'synthetic'}}})
    monkeypatch.setattr(setup,'_create_tracker_instance',lambda t:SimpleNamespace(trumping_url='https://example.org/api/'))
    post=AsyncMock(side_effect=AssertionError('must not POST'))
    monkeypatch.setattr('src.trackersetup.httpx.AsyncClient',post)
    m=Meta(were_trumping=True,tracker_status={'LST':{'upload_success':True,'torrent_id':'99'}})
    m['LST_reported_torrent_id']='42';m['LST_were_trumping']=True;m['LST_protected_ids']=['42']
    assert await setup.make_trumpable_report(m,'LST') is False
    post.assert_not_called()


@pytest.mark.asyncio
async def test_dupe_force_cannot_bypass_prohibited_format(monkeypatch):
    result=decide(p('720p.BluRay.x265-A'))
    helper=UploadHelper({'DEFAULT':{}})
    prompt=AsyncMock(side_effect=AssertionError('must not prompt'))
    monkeypatch.setattr(helper,'prompt_yes_no',prompt)
    rejected,m=await helper.dupe_check([],Meta(unattended=False,dupe=True),'LST',result)
    assert rejected is True and m['LST_cross_seed'] is False


@pytest.mark.asyncio
async def test_registry_internal_whitelist_and_full_disc_support():
    m=Meta(category='MOVIE',type='DISC',is_disc='BDMV',resolution='1080p',container='BDMV')
    result=await evaluate_slots([],m,'LST',{})
    assert result.verdict is REVIEW and result.requires_evidence


def test_dead_torrent_is_conditional_not_an_internal_override():
    old=p('1080p.WEB-DL.H264-A',id=42,seeders=0)
    assert decide(p('1080p.WEB-DL.H264-B'),old).verdict is REVIEW
    result=decide(p('1080p.WEB-DL.H264-B'),replace(old,internal=True))
    assert result.protected_ids==['42'] and not result.trump_recommended


def test_remux_master_or_asset_coexistence_requires_evidence():
    result=decide(p('1080p.BluRay.REMUX.AVC-A'),p('1080p.BluRay.REMUX.AVC-B',id=42))
    assert result.verdict is REVIEW and result.requires_evidence


@pytest.mark.asyncio
@pytest.mark.parametrize('internal,groups,protected',[(False,['GRP'],['42']),(True,['OTHER'],['42']),(True,['GRP'],[])])
async def test_internal_status_is_not_inferred_from_matching_filename_group(monkeypatch,internal,groups,protected):
    monkeypatch.setattr('src.slot_rules.registry._provider',AsyncMock(return_value='AMZN'))
    m=Meta(category='MOVIE',type='WEBDL',resolution='1080p',video_codec='AVC',container='mkv',service='AMZN',tag='-GRP',repack='REPACK',name='Film.2020.REPACK.1080p.AMZN.WEB-DL.H264-GRP')
    old={'name':'Film.2020.1080p.AMZN.WEB-DL.H264-GRP','id':42,'internal':True}
    result=await evaluate_slots([old],m,'LST',{'TRACKERS':{'LST':{'internal':internal,'internal_groups':groups}}})
    assert result.protected_ids==protected

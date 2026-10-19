"""HDBits-specific recommendations, not HD-Torrents and not quality guesses."""
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from src.meta import Meta
from src.slot_rules.models import Verdict
from src.slot_rules.profile import profile_from_entry
from src.slot_rules.registry import evaluate_slots, has_slot_rules
from src.slot_rules.trackers.hdbits import HDBitsSlotRules
from src.uphelper import UploadHelper

ALLOW, BLOCK, REVIEW = Verdict.ALLOW, Verdict.BLOCK, Verdict.REVIEW


def p(name, **fields):
    return profile_from_entry({'name':'Film.2020.'+name,**fields})


def decide(candidate,*existing,meta=None):
    return HDBitsSlotRules(meta).evaluate(candidate,existing)


def test_distinct_hdbits_registration():
    assert has_slot_rules('HDBITS') and has_slot_rules('HDTORRENTS')


@pytest.mark.parametrize('group',['CDDHD','EuReKA','DDR','EVO','DNL','BARC0DE','SPiRiT'])
def test_banned_encode_groups(group):
    assert decide(p('1080p.BluRay.x264-'+group)).verdict is BLOCK


@pytest.mark.parametrize('name',['720p.WEB-DL.HDR10.H265-A','720p.BluRay.HDR10.x265-A'])
def test_720p_hdr_is_prohibited(name):
    assert decide(p(name)).verdict is BLOCK


@pytest.mark.parametrize('name',['1080p.WEB-DL.H265-A','720p.BluRay.x265-A'])
def test_hd_hevc_needs_quality_and_bitrate_proof(name):
    result=decide(p(name))
    assert result.verdict is REVIEW and result.requires_evidence
    assert '20%' in result.reason and 'bitrate' in result.reason


def test_ten_bit_avc_needs_same_proof():
    result=decide(replace(p('1080p.WEB-DL.H264-A'),hi10p=True))
    assert result.verdict is REVIEW and result.requires_evidence


def test_encode_reservations_and_transparency_are_not_assumed():
    result=decide(p('1080p.BluRay.x264-A'))
    assert result.verdict is REVIEW and result.requires_evidence
    assert 'lottery' in result.why and 'audio' in result.why


def test_internal_replacement_compares_sources_and_quality_not_size():
    result=decide(p('1080p.BluRay.x264-A',size=10**10),p('1080p.BluRay.x264-B',size=2*10**10,internal=True))
    assert result.verdict is REVIEW and not result.trump_recommended
    assert '5-10' in result.why and 'transparent' in result.why


def test_remux_needs_logs_native_audio_and_rights():
    result=decide(p('2160p.BluRay.REMUX.HEVC-A'))
    assert result.verdict is REVIEW and result.requires_evidence
    assert '3.52' in result.why and '48 hours' in result.why and 'FLAC' in result.why


def test_non3d_iso_prohibited():
    meta=Meta(path='/tmp/movie.iso',container='iso')
    assert decide(p('1080p.BluRay.COMPLETE-A',type='DISC'),meta=meta).verdict is BLOCK


def test_3d_iso_needs_complete_disc_evidence_not_automatic_rejection():
    meta=Meta(path='/tmp/movie.iso',container='iso')
    assert decide(p('1080p.3D.BluRay.COMPLETE-A',type='DISC'),meta=meta).verdict is REVIEW


def test_descriptive_audio_is_prohibited():
    meta=Meta(mediainfo={'media':{'track':[{'@type':'Audio','Title':'English Audio Description'}]}})
    assert decide(p('2160p.WEB-DL.H265-A'),meta=meta).verdict is BLOCK


def test_movie_title_ad_does_not_mean_descriptive_audio():
    assert decide(p('Ad.Astra.2160p.WEB-DL.H265-A')).verdict is ALLOW


def test_known_nonanimated_dubs_prohibited():
    meta=Meta();meta['has_muxed_dubs']=True;meta['is_animation']=False
    assert decide(p('2160p.WEB-DL.H265-A'),meta=meta).verdict is BLOCK


def test_known_missing_forced_subtitles_prohibited():
    meta=Meta();meta['HDBITS_missing_forced_subtitles']=True
    assert decide(p('2160p.WEB-DL.H265-A'),meta=meta).verdict is BLOCK


def test_tv_signup_rights_and_packs_require_verification():
    result=decide(p('2160p.WEB-DL.H265-A'),meta=Meta(category='TV'))
    assert result.verdict is REVIEW and '48-hour' in result.reason


def test_known_single_episode_folder_is_not_allowed():
    meta=Meta(category='TV',tv_pack=0);meta['HDBITS_torrent_has_episode_folder']=True
    assert decide(p('2160p.WEB-DL.H265-A'),meta=meta).verdict is BLOCK


def test_movies_anywhere_4k_comparison_exception():
    candidate=p('2160p.MA.WEB-DL.H265-A')
    old=p('1080p.BluRay.x264-B',internal=True)
    assert decide(candidate,old,meta=Meta(service='MA')).verdict is ALLOW
    assert decide(candidate,old,meta=Meta(service='AMZN')).verdict is REVIEW


def test_720p_web_comparison_exception():
    assert decide(p('720p.WEB-DL.H264-A'),p('1080p.BluRay.x264-B',internal=True)).verdict is ALLOW


def test_explicit_dead_release_exception_not_inferred_from_missing_seeders():
    candidate=p('2160p.WEB-DL.H265-A')
    assert decide(candidate,p('1080p.BluRay.x264-B',dead=True)).verdict is ALLOW
    assert decide(candidate,p('1080p.BluRay.x264-B',seeders=0)).verdict is REVIEW


def test_no_assumed_provider_or_dynamic_range_extra_slots():
    result=decide(p('2160p.MA.WEB-DL.H265-A'),p('2160p.AMZN.WEB-DL.DV.HDR10.H265-B'))
    assert result.verdict is REVIEW


def test_numeric_resolution_api_field_falls_back_to_release_name():
    existing=p('2160p.WEB-DL.H265-B',res='3')
    assert decide(p('2160p.WEB-DL.H265-A'),existing).verdict is REVIEW


@pytest.mark.asyncio
async def test_registry_and_unattended_evidence_gate(monkeypatch):
    meta=Meta(category='MOVIE',type='REMUX',resolution='2160p',source='BluRay',name='Film.2160p.BluRay.REMUX.HEVC-A',video_codec='HEVC')
    result=await evaluate_slots([],meta,'HDBITS',{})
    assert result.verdict is REVIEW and result.requires_evidence
    helper=UploadHelper({'DEFAULT':{}})
    prompt=AsyncMock(side_effect=AssertionError('must not prompt unattended'))
    monkeypatch.setattr(helper,'prompt_yes_no',prompt)
    meta.unattended=True
    rejected,meta=await helper.dupe_check([],meta,'HDBITS',result)
    assert rejected is True and meta['HDBITS_cross_seed'] is False
    prompt.assert_not_awaited()

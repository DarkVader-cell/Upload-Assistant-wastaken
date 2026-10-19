"""BLU supplied rules: source-specific coexistence and evidence, never metadata rank."""

# ruff: noqa: S101
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from src.meta import Meta
from src.slot_rules.models import Verdict
from src.slot_rules.profile import profile_from_entry, profile_from_meta
from src.slot_rules.registry import evaluate_slots, has_slot_rules
from src.slot_rules.trackers.blutopia import DERIVED_DV_ALERT, BlutopiaSlotRules, track_family
from src.trackers.UNIT3D.blutopia import Blutopia
from src.uphelper import UploadHelper


def p(name, provider="AMZN", **extra):
    return profile_from_entry({"name": "Film.2020." + name, **extra}, provider=provider)


def meta(**extra):
    m = Meta(
        category="MOVIE",
        name="Film.2020.1080p.AMZN.WEB-DL.H264-TEST",
        type="WEBDL",
        resolution="1080p",
        source="WEB",
        service="AMZN",
        video_codec="AVC",
        container="mkv",
        original_language="en",
        image_list=[{"raw_url": "https://example.org/screenshot.png"}] * 3,
        mediainfo={"media": {"track": [{"@type": "Audio", "Format": "FLAC", "Channels": "2", "Language": "en"}]}},
    )
    for k, v in extra.items():
        m[k] = v
    return m


def decide(new=None, *old, m=None):
    if new is None:
        new = profile_from_meta(m)
    return BlutopiaSlotRules(m).evaluate(new, old)


def test_registered_and_full_title_search():
    assert has_slot_rules("BLUTOPIA") and Blutopia.search_whole_title


def test_ordinary_native_web_vacancy_is_not_blanket_review():
    result = decide(m=meta())
    assert result.verdict is Verdict.ALLOW and not result.trump_recommended


@pytest.mark.parametrize("name", ["480p.BluRay.x264-TEST", "1440p.BluRay.x265-TEST", "1080p.BluRay.AV1-TEST"])
def test_known_encode_prohibitions(name):
    result = decide(p(name))
    assert result.verdict is Verdict.BLOCK and result.constraint_violation


@pytest.mark.parametrize(
    "key,value",
    [
        ("BLUTOPIA_invalid_hybrid", True),
        ("BLUTOPIA_banned_group", True),
        ("sportscast", True),
        ("music_video", True),
        ("bootleg", True),
        ("personally_identifying_content", True),
        ("BLUTOPIA_extraneous_files", ["sample.mkv"]),
        ("BLUTOPIA_tools_used", ["/opt/tools/hdr10plus_tool.exe"]),
        ("BLUTOPIA_tools_used", ["truehdd"]),
        ("BLUTOPIA_hdr10plus_injected_with_hdr10plus_tool", True),
        ("service", "YouTube"),
    ],
)
def test_known_prohibited_content_and_tools(key, value):
    result = decide(m=meta(**{key: value}))
    assert result.verdict is Verdict.BLOCK and result.constraint_violation


def test_prohibited_tool_word_is_not_evidence_of_usage():
    assert decide(m=meta(name="Film.about.truehdd.2020.1080p.WEB-DL.H264-TEST")).verdict is Verdict.ALLOW


def test_banned_group_uses_actual_blu_list():
    assert decide(p("1080p.WEB-DL.H264-FGT")).verdict is Verdict.BLOCK


@pytest.mark.parametrize("provider,codec", [("NF", "H264"), ("AMZN", "H265")])
def test_provider_or_codec_coexistence_not_unrelated_target(provider, codec):
    result = decide(p(f"1080p.WEB-DL.{codec}-NEW", provider), p("1080p.WEB-DL.H264-OLD", id=42))
    assert not result.conflicts and not result.trump_recommended


def test_hdr10_and_dv_metadata_are_not_separate_same_colour_space_slots():
    result = decide(p("2160p.WEB-DL.DV.HDR10.H265-NEW"), p("2160p.WEB-DL.HDR10.H265-OLD", id=42))
    assert result.verdict is Verdict.REVIEW and result.conflicts[0]["id"] == 42
    assert not result.trump_recommended


def test_hdr_sdr_native_web_combination_not_unrelated_target():
    result = decide(p("2160p.WEB-DL.H265-NEW"), p("2160p.WEB-DL.HDR10.H265-OLD", id=42))
    assert not result.conflicts


def test_derived_original_pair_requires_evidence_without_original_trump():
    new = replace(p("2160p.WEB-DL.DV.HDR10.H265-NEW"), hybrid=True)
    result = decide(new, p("2160p.WEB-DL.HDR10.H265-OLD", id=42))
    assert result.verdict is Verdict.REVIEW and result.requires_evidence
    assert not result.conflicts and not result.trump_recommended


def test_web_dovi_declared_derived_cannot_keep_hybrid_title():
    result = decide(m=meta(webdv=True, name="Film.2020.HYBRID.1080p.WEB-DL.H264-TEST"))
    assert result.verdict is Verdict.BLOCK and result.constraint_violation


@pytest.mark.parametrize("fanres", [False, True])
def test_derived_remux_requires_real_fanres_route_and_description_evidence(fanres):
    m = meta(type="REMUX", source="BluRay", webdv=True, edition="FANRES" if fanres else "")
    result = decide(m=m)
    if fanres:
        assert result.verdict is Verdict.REVIEW and result.requires_evidence
        assert DERIVED_DV_ALERT in result.why and "Metafier" in result.why and "PQ" in result.why
    else:
        assert result.verdict is Verdict.BLOCK and result.constraint_violation


def test_tv_fanres_edition_alone_is_not_actual_category_route():
    m = meta(category="TV", type="REMUX", webdv=True, edition="FANRES")
    assert decide(m=m).verdict is Verdict.BLOCK
    m.tracker_status = {"BLUTOPIA": {"other": True}}
    assert decide(m=m).verdict is Verdict.REVIEW


@pytest.mark.parametrize("count,resolution", [(1, "720p"), (2, "1080p"), (1, "2160p")])
def test_encode_caps_are_not_multiplied_per_codec_provider_hdr(count, resolution):
    old = [p(f"{resolution}.BluRay.x264-G{i}", id=i) for i in range(count)]
    result = decide(p(f"{resolution}.WEBRip.HDR10.x265-NEW", "NF"), *old)
    assert result.verdict is Verdict.REVIEW and len(result.conflicts) == count
    assert "1x720p, 2x1080p, 1x2160p" in result.reason


def test_webrip_needs_comparison_even_different_resolution_from_web_source():
    result = decide(p("1080p.WEBRip.x264-NEW"), p("2160p.WEB-DL.H265-OLD", id=42))
    assert "significant visual improvement" in result.why and result.requires_evidence


def test_remux_profiles_do_not_automatically_trump_by_number():
    result = decide(p("2160p.BluRay.REMUX.DV.HDR10.HEVC-NEW"), p("2160p.BluRay.REMUX.DV.HDR10.HEVC-OLD", id=42))
    assert result.verdict is Verdict.REVIEW and not result.trump_recommended


@pytest.mark.parametrize("group", ["NEW", "OLD"])
def test_reissue_is_only_claimed_for_verified_original_group(group):
    result = decide(p(f"1080p.WEB-DL.H264.RE-ISSUE-{group}"), p("1080p.WEB-DL.H264-OLD", id=42))
    assert result.verdict is Verdict.REVIEW
    assert ("RE-ISSUE" in result.reason) == (group == "OLD")


def test_sd_web_exception_is_not_proven_by_empty_search():
    result = decide(p("576p.WEB-DL.H264-NEW"))
    assert result.verdict is Verdict.REVIEW and "never-HD OAR" in result.why


def test_zero_seeders_does_not_prove_dead_reseed_age():
    result = decide(p("1080p.WEB-DL.H264-NEW"), p("1080p.WEB-DL.H264-OLD", id=42, seeders=0))
    assert result.verdict is Verdict.REVIEW and not result.trump_recommended
    assert "seed count alone" in " ".join(result.notes)


@pytest.mark.parametrize(
    "fmt,channels,anime,blocked",
    [
        ("FLAC", "6", False, True),
        ("FLAC", "6", True, False),
        ("FLAC", "8", True, True),
        ("AAC", "6", True, True),
        ("Opus", "2", False, True),
        ("Vorbis", "2", False, True),
        ("MPEG Audio", "2", False, True),
    ],
)
def test_encode_audio_known_prohibitions_and_anime_exceptions(fmt, channels, anime, blocked):
    m = meta(type="ENCODE", source="BluRay", anime=anime, mediainfo={"media": {"track": [{"@type": "Audio", "Format": fmt, "Channels": channels, "Language": "en"}]}})
    result = decide(m=m)
    assert (result.verdict is Verdict.BLOCK) == blocked


def test_mpeg_layer2_is_not_misclassified_as_mp3():
    assert track_family({"Format": "MPEG Audio", "Format_Profile": "Layer 2"}) == "mp2"
    m = meta(type="HDTV", mediainfo={"media": {"track": [{"@type": "Audio", "Format": "MPEG Audio", "Format_Profile": "Layer 2", "Channels": "2"}]}})
    result = decide(m=m)
    assert result.verdict is Verdict.REVIEW and "MP2" in result.why


def test_truehd_compat_requires_ac3_bsid6_not_ddplus():
    tracks = [{"@type": "Audio", "Format": "MLP FBA", "Channels": "6", "Language": "en"}, {"@type": "Audio", "Format": "E-AC-3", "Channels": "6", "Language": "en"}]
    m = meta(mediainfo={"media": {"track": tracks}})
    assert decide(m=m).verdict is Verdict.BLOCK
    tracks[1] = {"@type": "Audio", "Format": "AC-3", "Channels": "6", "Language": "en", "extra": {"bsid": "8"}}
    assert decide(m=m).verdict is Verdict.BLOCK
    tracks[1]["extra"]["bsid"] = "6"
    assert decide(m=m).verdict is Verdict.REVIEW


def test_sdr_live_action_x265_not_inferred_for_unknown_animation():
    m = meta(type="ENCODE", video_codec="HEVC", genres=["Action"])
    assert decide(m=m).verdict is Verdict.BLOCK
    m.genres = ["Animation"]
    assert decide(m=m).verdict is Verdict.REVIEW


def test_uhd_encode_dub_or_compat_default_is_not_main_audio_identity():
    m = meta(type="ENCODE", resolution="2160p", video_codec="HEVC", hdr="HDR", genres=["Animation"])
    m.mediainfo = {"media": {"track": [{"@type": "Audio", "Format": "E-AC-3", "Language": "en", "Channels": "6"}]}}
    assert decide(m=m).verdict is Verdict.BLOCK
    m.mediainfo["media"]["track"].append({"@type": "Audio", "Format": "FLAC", "Language": "en", "Channels": "2", "Default": "No"})
    assert decide(m=m).verdict is Verdict.REVIEW


@pytest.mark.parametrize("hours,episode,blocked", [(73, "E02", True), (71, "E02", False), (73, "E01", False)])
def test_source_release_grace_not_airdate_and_pilot_exception(hours, episode, blocked):
    m = meta(category="TV", season="S01", episode=episode, season_completed=True, BLUTOPIA_source_released_at=(datetime.now(UTC) - timedelta(hours=hours)).isoformat())
    assert (decide(m=m).verdict is Verdict.BLOCK) == blocked


def test_unverified_or_naive_source_time_requires_review():
    m = meta(category="TV", season="S01", episode="E02", season_completed=True, BLUTOPIA_source_released_at="2020-01-01T00:00:00")
    assert decide(m=m).requires_evidence


def test_web_concert_needs_actual_mod_queue_then_staff_review():
    m = meta(BLUTOPIA_concert=True)
    assert decide(m=m).verdict is Verdict.BLOCK
    m["BLUTOPIA_modq_effective"] = True
    result = decide(m=m)
    assert result.requires_evidence and "forum staff approval" in result.why


@pytest.mark.parametrize("kind,container,allowed", [("WEBDL", "mp4", False), ("WEBDL", "mkv", True), ("HDTV", "ts", True), ("REMUX", "mp4", False)])
def test_containers_not_arbitrarily_inherited_from_other_trackers(kind, container, allowed):
    result = decide(m=meta(type=kind, container=container))
    assert (result.verdict is Verdict.BLOCK) != allowed


def test_confirmed_profile5_mp4_not_bare_dv():
    m = meta(container="mp4", hdr="DV", mediainfo={"media": {"track": [{"@type": "Video", "HDR_Format_Profile": "dvhe.05.06"}]}})
    assert decide(m=m).verdict is Verdict.REVIEW
    m.mediainfo = {}
    assert decide(m=m).verdict is Verdict.REVIEW and "Profile 5 proof" in decide(m=m).why


@pytest.mark.asyncio
async def test_registry_disc_support_and_fail_closed(monkeypatch):
    m = meta(type="DISC", is_disc="BDMV", container="BDMV")
    assert (await evaluate_slots([], m, "BLUTOPIA", {})).requires_evidence
    monkeypatch.setattr(BlutopiaSlotRules, "evaluate", lambda *_args: 1 / 0)
    result = await evaluate_slots([], m, "BLUTOPIA", {})
    assert result.verdict is Verdict.REVIEW and result.requires_evidence


@pytest.mark.asyncio
async def test_no_duplicate_override_for_known_must_violation(monkeypatch):
    result = decide(p("1080p.BluRay.AV1-NEW"))
    helper = UploadHelper({"DEFAULT": {}})
    prompt = AsyncMock(side_effect=AssertionError("must not prompt"))
    monkeypatch.setattr(helper, "prompt_yes_no", prompt)
    rejected, m = await helper.dupe_check([], Meta(dupe=True), "BLUTOPIA", result)
    assert rejected and m["BLUTOPIA_cross_seed"] is False
    prompt.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("unattended", [True, False])
async def test_required_evidence_gate_even_vacant_no_cross_seed(monkeypatch, unattended):
    result = decide(p("1080p.BluRay.x264-NEW"))
    helper = UploadHelper({"DEFAULT": {}})
    prompt = AsyncMock(return_value=False)
    monkeypatch.setattr(helper, "prompt_yes_no", prompt)
    rejected, m = await helper.dupe_check([], Meta(unattended=unattended), "BLUTOPIA", result)
    assert rejected and m["BLUTOPIA_cross_seed"] is False
    if unattended:
        prompt.assert_not_called()
    else:
        assert prompt.call_args.kwargs["default"] is False


@pytest.mark.parametrize("profile", ["dvhe.07.06", "dvhe.08.06"])
def test_known_nonprofile5_mp4_cannot_be_overridden_by_edition(profile):
    m = meta(container="mp4", hdr="DV", edition="DV Profile 5", mediainfo={"media": {"track": [{"@type": "Video", "HDR_Format_Profile": profile}]}})
    assert decide(m=m).verdict is Verdict.BLOCK


def test_structured_hybrid_flag_without_forbidden_web_title():
    old = p("2160p.WEB-DL.DV.HDR10.H265-OLD", id=42, hybrid=True)
    result = decide(p("2160p.WEB-DL.HDR10.H265-NEW"), old)
    assert result.requires_evidence and not result.conflicts and not result.trump_recommended


def test_known_dvd_iso_not_allowed_by_fake_3d_exception():
    m = meta(type="DISC", is_disc="DVD", container="iso")
    assert decide(p("1080p.3D.COMPLETE.BluRay", type="DISC"), m=m).constraint_violation


def test_known_mvc_disc_folders_require_iso():
    m = meta(type="DISC", is_disc="BDMV", container="BDMV", BLUTOPIA_mvc=True)
    assert decide(p("1080p.3D.COMPLETE.BluRay", type="DISC"), m=m).constraint_violation


@pytest.mark.parametrize("library", ["NVENC", "Intel Quick Sync", "ATEME Titan"])
def test_known_non_x264_x265_encoder_is_not_bypassed(library):
    m = meta(type="ENCODE", mediainfo={"media": {"track": [{"@type": "Video", "Encoded_Library_Name": library}]}})
    assert decide(m=m).constraint_violation


def test_personal_release_should_failures_are_must():
    m = meta(personalrelease=True, BLUTOPIA_should_failures=["missing applicable primary-source commentary"])
    assert decide(m=m).constraint_violation
    m.personalrelease = False
    assert not decide(m=m).constraint_violation


def test_prehosted_capture_manifest_counts_before_image_upload(monkeypatch):
    monkeypatch.setattr("src.slot_rules.trackers.blutopia.manifest_files", lambda *_args: ["frame1.png", "frame2.png", "frame3.png"])
    m = meta(image_list=[], uuid="synthetic", base_dir="/unused")
    assert decide(m=m).verdict is Verdict.ALLOW


def test_known_non_anime_hi10p_is_not_a_manual_loophole():
    m = meta(type="ENCODE", genres=["Action"])
    new = p("1080p.BluRay.x264.Hi10P-TEST")
    assert decide(new, m=m).constraint_violation
    m.anime = True
    assert decide(new, m=m).verdict is Verdict.REVIEW


@pytest.mark.asyncio
async def test_complete_series_remains_visible_to_individual_season(monkeypatch):
    monkeypatch.setattr("src.slot_rules.registry._provider", AsyncMock(return_value="AMZN"))
    m = meta(category="TV", season="S01", tv_pack=True)
    result = await evaluate_slots([{"name": "Film.2020.Complete.Series.1080p.AMZN.WEB-DL.H264-OLD", "id": 42}], m, "BLUTOPIA", {})
    assert result.verdict is Verdict.REVIEW and result.conflicts[0]["id"] == 42
    assert "COMPLETE series" in result.why

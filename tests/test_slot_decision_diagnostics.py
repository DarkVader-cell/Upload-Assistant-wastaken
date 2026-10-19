"""Slot causes are named without turning context releases into report targets."""

# ruff: noqa: S101
from dataclasses import replace

import pytest

from src.meta import Meta
from src.slot_rules.models import Verdict
from src.slot_rules.profile import profile_from_entry, profile_from_meta
from src.slot_rules.registry import evaluate_slots
from src.slot_rules.trackers.aither import AitherSlotRules
from src.slot_rules.trackers.blutopia import BlutopiaSlotRules
from src.slot_rules.trackers.lst import LstSlotRules
from src.uphelper import UploadHelper


def p(name, **fields):
    return profile_from_entry({"name": "Film.2020." + name, **fields}, provider="AMZN")


def render(monkeypatch, decision, embed=True):
    lines = []
    monkeypatch.setattr("src.uphelper.logger.info", lambda message, **_kw: lines.append(str(message)))
    UploadHelper({"DEFAULT": {"embed_links": embed}})._show_slot_decision(decision, Meta())
    return " ".join(lines)


def test_pair_reason_names_existing_release_and_leaves_raw_targets_unchanged(monkeypatch):
    old = p("2160p.WEB-DL.DV.HDR.H265-OLD", id=42, link="https://example.org/torrents/42")
    decision = AitherSlotRules().evaluate(p("2160p.WEB-DL.HDR.H265-NEW"), [old])
    assert decision.conflicts == [dict(old.entry)]
    assert decision.comparisons[0]["id"] == 42 and "already has Dolby Vision" in decision.comparisons[0]["reason"]
    text = render(monkeypatch, decision)
    assert "#42" in text and old.name in text and "Affects this check:" in text


def test_release_name_still_prints_when_embedded_links_are_disabled(monkeypatch):
    old = p("2160p.WEB-DL.HDR.H265-OLD", id=42, link="https://example.org/torrents/42")
    decision = AitherSlotRules().evaluate(p("2160p.WEB-DL.HDR.H265-NEW"), [old])
    text = render(monkeypatch, decision, embed=False)
    assert old.name in text and "https://example.org/torrents/42" in text


@pytest.mark.parametrize("tracker", ["aither", "lst"])
def test_hd_prerequisite_identifies_actor_without_making_trump_target(tracker):
    rules = AitherSlotRules() if tracker == "aither" else LstSlotRules()
    old = p("1080p.BluRay.REMUX.AVC-OLD", id=99)
    decision = rules.evaluate(p("480p.WEB-DL.H264-NEW"), [old])
    assert decision.verdict is Verdict.BLOCK and not decision.conflicts
    assert decision.related_releases[0]["id"] == 99 and not decision.trump_recommended


def test_aither_1440_names_2160_prerequisite():
    old = p("2160p.WEB-DL.H265-OLD", id=99)
    decision = AitherSlotRules().evaluate(p("1440p.WEB-DL.H264-NEW"), [old])
    assert not decision.conflicts and decision.related_releases[0]["id"] == 99


def test_blu_web_source_is_context_not_automatic_report_target(monkeypatch):
    old = p("2160p.WEB-DL.H265-OLD", id=123)
    decision = BlutopiaSlotRules().evaluate(p("1080p.WEBRip.x264-NEW"), [old])
    assert not decision.conflicts and decision.related_releases[0]["id"] == 123
    assert decision.requirements and "significant visual improvement" in " ".join(decision.requirements)
    text = render(monkeypatch, decision)
    assert "#123" in text and "context only" in text
    assert "No specific existing release" not in text


def test_bluray_encode_not_given_unrelated_web_source_restriction():
    decision = BlutopiaSlotRules().evaluate(p("1080p.BluRay.x264-NEW"), [p("2160p.WEB-DL.H265-OLD", id=123)])
    assert not decision.related_releases
    assert "WEBRip cannot coexist" not in " ".join(decision.requirements)


def test_blu_native_derived_reference_is_not_report_target():
    original = p("2160p.WEB-DL.HDR10.H265-OLD", id=42)
    incoming = replace(p("2160p.WEB-DL.DV.HDR10.H265-NEW"), hybrid=True)
    decision = BlutopiaSlotRules().evaluate(incoming, [original])
    assert not decision.conflicts and decision.related_releases[0]["id"] == 42


def test_upload_only_evidence_check_says_no_identified_existing_cause(monkeypatch):
    m = Meta(type="WEBDL", category="MOVIE", resolution="1080p", video_codec="AVC", service="AMZN", container="mkv")
    decision = BlutopiaSlotRules(m).evaluate(profile_from_meta(m), [])
    assert not decision.conflicts and not decision.related_releases
    assert any("Screenshots: 0" in x for x in decision.requirements)
    text = render(monkeypatch, decision)
    assert "Required checks for this upload" in text and "No specific existing release" in text
    assert "Seed ≥7 days" not in text


@pytest.mark.asyncio
async def test_failed_search_never_claims_vacant_slot_or_uses_stale_title_cache():
    m = Meta(type="WEBDL", category="MOVIE", resolution="2160p", video_codec="HEVC", hdr="HDR")
    m["AITHER_search_failed"] = True
    m["AITHER_title_releases"] = [{"name": "Stale.2160p.WEB-DL.HDR.H265-OLD", "id": 77}]
    decision = await evaluate_slots([], m, "AITHER", {})
    assert decision.verdict is Verdict.REVIEW and decision.requires_evidence
    assert not decision.conflicts and "occupancy is unknown" in decision.reason


@pytest.mark.asyncio
async def test_failed_search_does_not_override_known_must_prohibition():
    m = Meta(type="ENCODE", category="MOVIE", resolution="480p", video_codec="AVC")
    m["BLUTOPIA_search_failed"] = True
    decision = await evaluate_slots([], m, "BLUTOPIA", {})
    assert decision.verdict is Verdict.BLOCK and decision.constraint_violation

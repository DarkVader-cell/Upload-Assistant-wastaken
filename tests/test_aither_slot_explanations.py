"""Aither's explicit matrix/priority must survive metadata aliases and be explained."""

# ruff: noqa: S101
import pytest

from src.meta import Meta
from src.slot_rules.models import Verdict
from src.slot_rules.profile import DV, HDR10, HDR10P, hdr_from_meta_value, profile_from_entry, profile_from_meta
from src.slot_rules.trackers.aither import AitherSlotRules
from src.uphelper import UploadHelper


def p(suffix):
    return profile_from_entry({"name": "Example.2020." + suffix})


@pytest.mark.parametrize("value", ["DV HDR", "DV/HDR", "DV.HDR", "DV_HDR", "DV-HDR", "DOVI HDR", "Dolby Vision / HDR10", "[DV] [HDR]"])
def test_dv_hdr_metadata_aliases_preserve_aither_trump(value):
    m = Meta(category="MOVIE", type="WEBDL", resolution="2160p", video_codec="HEVC", hdr=value)
    upload = profile_from_meta(m)
    assert upload.hdr == frozenset({DV, HDR10})
    result = AitherSlotRules(m).evaluate(upload, [p("2160p.WEB-DL.HDR.H265-OLD")])
    assert result.verdict is Verdict.ALLOW and result.trump_recommended
    assert "DV/HDR takes precedence" in result.why
    assert any("Aither rule:" in n and "DV/HDR trumps HDR" in n for n in result.notes)


@pytest.mark.parametrize("value", ["DV/HDR10+", "DOVI HDR10PLUS", "DV_HDR10P"])
def test_hdr10plus_aliases_preserve_combined_priority(value):
    assert hdr_from_meta_value(value) == frozenset({DV, HDR10P})
    m = Meta(category="MOVIE", type="WEBDL", resolution="2160p", video_codec="HEVC", hdr=value)
    result = AitherSlotRules(m).evaluate(profile_from_meta(m), [p("2160p.WEB-DL.HDR10+.H265-OLD")])
    assert result.verdict is Verdict.ALLOW and result.trump_recommended


@pytest.mark.parametrize("new,old", [("HDR", "HDR"), ("DV.HDR", "DV.HDR"), ("HDR", "DV.HDR")])
def test_block_explains_detected_formats_and_real_priority(new, old):
    result = AitherSlotRules().evaluate(p(f"2160p.WEB-DL.{new}.H265-NEW"), [p(f"2160p.WEB-DL.{old}.H265-OLD")])
    assert result.verdict is Verdict.BLOCK
    assert "Detected incoming:" in result.why and "existing:" in result.why
    assert "No supplied rule establishes" not in result.why
    assert any("DV/HDR trumps HDR" in n for n in result.notes)


@pytest.mark.parametrize("resolution", ["1080p", "2160p"])
@pytest.mark.parametrize("format_name", ["WEB-DL.H265", "BluRay.x265"])
def test_explicit_native_dv_over_hdr_priority(resolution, format_name):
    result = AitherSlotRules().evaluate(p(f"{resolution}.DV.HDR.{format_name}-NEW"), [p(f"{resolution}.HDR.{format_name}-OLD")])
    assert result.verdict is Verdict.ALLOW and result.trump_recommended


def test_actual_metadata_not_filename_grants_dv_upgrade():
    m = Meta(name="Example.2020.2160p.WEB-DL.DV.HDR.H265-NEW", type="WEBDL", resolution="2160p", video_codec="HEVC", hdr="HDR")
    upload = profile_from_meta(m)
    assert upload.hdr == frozenset({HDR10})
    result = AitherSlotRules(m).evaluate(upload, [p("2160p.WEB-DL.HDR.H265-OLD")])
    assert result.verdict is Verdict.BLOCK and "same detected dynamic range" in result.why


def test_terminal_explains_rule_and_detection(monkeypatch):
    lines = []
    monkeypatch.setattr("src.uphelper.logger.info", lambda message, **_kwargs: lines.append(str(message)))
    result = AitherSlotRules().evaluate(p("2160p.WEB-DL.HDR.H265-NEW"), [p("2160p.WEB-DL.HDR.H265-OLD")])
    UploadHelper({"DEFAULT": {}})._show_slot_decision(result, Meta())
    text = " ".join(lines)
    assert "Aither rule:" in text and "Detected incoming:" in text
    assert "DV/HDR trumps HDR" in text and "No supplied rule establishes" not in text


def test_dv_only_does_not_invent_hdr10_compatibility():
    assert hdr_from_meta_value("DOVI") == frozenset({DV})


def test_declared_web_dv_is_hybrid_not_proven_disc_dv():
    m = Meta(type="REMUX", resolution="2160p", source="BluRay", video_codec="HEVC", hdr="DV HDR", webdv=True)
    result = AitherSlotRules(m).evaluate(profile_from_meta(m), [p("2160p.BluRay.REMUX.HDR.HEVC-OLD")])
    assert result.verdict is Verdict.REVIEW and result.requires_evidence
    assert "grade checks" in result.reason


def test_hybrid_priority_is_explained_but_proof_not_waived():
    result = AitherSlotRules().evaluate(p("2160p.HYBRID.BluRay.x265.DV.HDR10+-NEW"), [p("2160p.HYBRID.BluRay.x265.HDR10+-OLD")])
    assert result.verdict is Verdict.REVIEW and result.requires_evidence
    assert any("DV/HDR10+ trumps DV/HDR and HDR10+" in n for n in result.notes)


@pytest.mark.parametrize(
    "name,prefix",
    [
        ("480p.WEB-DL.H264-GRP", ("SD", "WEB-DL")),
        ("480p.DVDRip.x264-GRP", ("SD", "DVDRip")),
        ("480p.DVD.REMUX.MPEG2-GRP", ("SD", "DVD Remux")),
        ("720p.WEB-DL.H264-GRP", ("720p", "WEB")),
        ("720p.BluRay.x264-GRP", ("720p", "encode")),
        ("1080p.WEB-DL.H264-GRP", ("1080p", "WEB", "H.264")),
        ("1080p.WEB-DL.DV.H265-GRP", ("1080p", "WEB", "DV")),
        ("1080p.WEB-DL.HDR.H265-GRP", ("1080p", "WEB", "HDR")),
        ("1080p.WEB-DL.DV.HDR.H265-GRP", ("1080p", "WEB", "HDR")),
        ("1080p.BluRay.x264-GRP", ("1080p", "x264 encode")),
        ("1080p.BluRay.x265-GRP", ("1080p", "x265 encode", "SDR")),
        ("1080p.BluRay.x265.DV.HDR-GRP", ("1080p", "x265 encode", "HDR")),
        ("1080p.HYBRID.BluRay.x265.DV.HDR10+-GRP", ("1080p", "x265 encode", "HYBRID")),
        ("1080p.BluRay.REMUX.AVC-GRP", ("1080p", "Remux")),
        ("1440p.WEB-DL.H264-GRP", ("1440p", "WEB", "H.264")),
        ("1440p.WEB-DL.DV.H265-GRP", ("1440p", "WEB", "DV")),
        ("1440p.WEB-DL.DV.HDR.H265-GRP", ("1440p", "WEB", "HDR")),
        ("2160p.WEB-DL.H265-GRP", ("2160p", "WEB", "SDR")),
        ("2160p.WEB-DL.DV.H265-GRP", ("2160p", "WEB", "DV")),
        ("2160p.WEB-DL.HDR.H265-GRP", ("2160p", "WEB", "HDR")),
        ("2160p.WEB-DL.DV.HDR.H265-GRP", ("2160p", "WEB", "HDR")),
        ("2160p.WEB-DL.HDR10+.H265-GRP", ("2160p", "WEB", "HDR10+")),
        ("2160p.WEB-DL.DV.HDR10+.H265-GRP", ("2160p", "WEB", "HDR10+")),
        ("2160p.BluRay.x265-GRP", ("2160p", "x265 encode", "SDR")),
        ("2160p.BluRay.x265.DV.HDR-GRP", ("2160p", "x265 encode", "HDR")),
        ("2160p.HYBRID.BluRay.x265.DV.HDR-GRP", ("2160p", "x265 encode", "HYBRID")),
        ("2160p.HYBRID.BluRay.x265.DV.HDR10+-GRP", ("2160p", "x265 encode", "HYBRID")),
        ("2160p.BluRay.REMUX.HEVC-GRP", ("2160p", "Remux", "SDR")),
        ("2160p.BluRay.REMUX.DV.HDR.HEVC-GRP", ("2160p", "Remux", "HDR")),
        ("2160p.HYBRID.BluRay.REMUX.DV.HDR10+.HEVC-GRP", ("2160p", "Remux", "HYBRID")),
    ],
)
def test_operator_matrix_slot_keys(name, prefix):
    key = AitherSlotRules().key(p(name))
    assert key[: len(prefix)] == prefix

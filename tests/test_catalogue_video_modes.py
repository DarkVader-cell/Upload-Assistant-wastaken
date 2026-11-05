# ruff: noqa: S101
"""Exact range overrides are per invocation and never mutate saved profiles."""

import pytest

from src.catalogue_runner import VIDEO_MODE_HDR, RunnerError, cardinal_command, video_mode_arguments


@pytest.mark.parametrize("mode", list(VIDEO_MODE_HDR))
def test_range_only_request_preserves_saved_resolution_and_codec(mode):
    arguments = video_mode_arguments({"video_mode": mode})
    assert arguments[:2] == ["--vq", "@@" + mode]
    assert "--fallback=false" in arguments
    assert ("--hybrid=true" in arguments) == mode.startswith("dv-")


def test_default_profile_is_unchanged():
    assert video_mode_arguments({}) == []


def test_invalid_range_not_executed():
    with pytest.raises(RunnerError):
        video_mode_arguments({"video_mode": "anything; arbitrary command"})


@pytest.mark.parametrize("mode", list(VIDEO_MODE_HDR))
def test_execution_snapshot_pins_exact_requested_range(mode):
    profile = {"hdr": list(VIDEO_MODE_HDR[mode]), "codec": "H265", "resolution": "2160p", "container": "mkv", "hybrid": mode.startswith("dv-")}
    arguments = cardinal_command({"video_mode": mode, "cardinal_binary": "fixture"}, {"service": "amazon", "item": "B012345678"}, profile)
    assert "2160p@hevc@" + mode in arguments and "--fallback=false" in arguments


def test_hdr10_alone_never_accepts_dv_or_hybrid():
    for profile in [{"hdr": ["HDR10", "DV"], "hybrid": True}, {"hdr": ["HDR10"], "hybrid": True}, {"hdr": [], "hybrid": False}]:
        with pytest.raises(RunnerError):
            cardinal_command(
                {"video_mode": "hdr10", "cardinal_binary": "fixture"},
                {"service": "amazon", "item": "B012345678"},
                {**profile, "codec": "H265", "resolution": "2160p", "container": "mkv"},
            )

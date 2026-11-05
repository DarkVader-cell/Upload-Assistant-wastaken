# ruff: noqa: S101
"""Metadata subprocess construction/file exchange, with all execution replaced."""

import json
from pathlib import Path

import pytest

import src.catalogue_metadata as metadata
from src.catalogue_runner import DOCKER_SUPERVISOR, RunnerError


@pytest.fixture
def settings(tmp_path):
    return {
        "cardinal_docker": {"container": "never-executed", "cli": "src/cli.js", "workdir": "/app/.output"},
        "cardinal_configpath": "/config/storage/storage.db",
        "cardinal_exchange_host": str(tmp_path / "exchange"),
        "cardinal_exchange_container": "/fixture-exchange",
        "timeout_seconds": 10,
    }


def candidate(episode="e1", number=1):
    return {
        "imdb": "tt1234567",
        "title": "Fixture",
        "year": 2024,
        "service": "netflix",
        "region": "US",
        "item": "series123",
        "series_item": "series123",
        "media_type": "episode",
        "season": 1,
        "season_id": "season-one",
        "episode": number,
        "episode_id": episode,
    }


def document(value):
    return {
        "schema": 1,
        "cli_sha256": metadata.CLI_SHA256,
        "service": "netflix",
        "requested": "series123",
        "selected_episode": value["episode_id"],
        "item": {"id": "series123", "title": "Fixture", "year": 2024},
        "seasons": [
            {
                "id": "season-one",
                "number": 1,
                "episodes": [
                    {
                        "id": value["episode_id"],
                        "episode": value["episode"],
                        "plan": {"ok": True, "codec": "H264", "resolution": "1080p", "container": "mkv", "hdr": [], "audio_languages": ["EN"], "subtitle_languages": []},
                    }
                ],
            }
        ],
    }


def test_episode_specific_command_exchange_and_cache(settings, monkeypatch):
    calls = []
    current = candidate()

    def fake_download(command, _timeout):
        calls.append(command)
        index = command.index(DOCKER_SUPERVISOR) + 2
        assert command[index].startswith("/fixture-exchange/probe-") and command[index].endswith(".cjs")
        assert command[index + 1] == "/app/.output/src/cli.js"
        assert command[command.index("--ua-episode-id") + 1] == current["episode_id"]
        assert command[command.index("--season") + 1] == "season-one"
        output = Path(settings["cardinal_exchange_host"]) / Path(command[command.index("--jsonoutput") + 1]).name
        output.write_text(json.dumps(document(current)))
        return "succeeded"

    monkeypatch.setattr(metadata, "download", fake_download)
    probe = metadata.MetadataProbe(settings)
    assert probe.item_profile(current)["codec"] == "H264"
    assert probe.item_profile(current)["codec"] == "H264" and len(calls) == 1
    current = candidate("e2", 2)
    assert probe.item_profile(current)["codec"] == "H264" and len(calls) == 2
    assert not list(Path(settings["cardinal_exchange_host"]).glob("listing-*.json"))


@pytest.mark.parametrize("fault", ["hash", "episode", "identity"])
def test_wrong_contract_and_identity_never_return_profile(settings, monkeypatch, fault):
    def fake_download(command, _timeout):
        value = document(candidate())
        if fault == "hash":
            value["cli_sha256"] = "unvalidated"
        elif fault == "episode":
            value["selected_episode"] = "other"
        else:
            value["item"]["imdb_id"] = "tt9999999"
        output = Path(settings["cardinal_exchange_host"]) / Path(command[command.index("--jsonoutput") + 1]).name
        output.write_text(json.dumps(value))
        return "succeeded"

    monkeypatch.setattr(metadata, "download", fake_download)
    with pytest.raises(RunnerError):
        metadata.MetadataProbe(settings).item_profile(candidate())
    assert not list(Path(settings["cardinal_exchange_host"]).glob("listing-*.json"))


def test_timeout_stops_metadata_run(settings, monkeypatch):
    monkeypatch.setattr(metadata, "download", lambda *_args: "uncertain")
    with pytest.raises(metadata.MetadataStopError):
        metadata.MetadataProbe(settings).item_profile(candidate())


@pytest.mark.parametrize("symlink", [False, True])
def test_public_or_symlink_exchange_is_rejected(settings, tmp_path, symlink):
    path = Path(settings["cardinal_exchange_host"])
    if symlink:
        target = tmp_path / "target"
        target.mkdir(mode=0o700)
        path.symlink_to(target, target_is_directory=True)
    else:
        path.mkdir(mode=0o755)
        path.chmod(0o755)
    with pytest.raises(RunnerError):
        metadata.MetadataProbe(settings).list(candidate())


def test_provider_unavailable_has_specific_sanitized_error(settings, monkeypatch):
    def fake_download(command, _timeout):
        value = {"schema": 1, "cli_sha256": metadata.CLI_SHA256, "service": "netflix", "requested": "series123", "error": {"code": "playback_unavailable"}}
        output = Path(settings["cardinal_exchange_host"]) / Path(command[command.index("--jsonoutput") + 1]).name
        output.write_text(json.dumps(value))
        return "failed"

    monkeypatch.setattr(metadata, "download", fake_download)
    with pytest.raises(metadata.PlaybackUnavailableError, match="no playable full-title offer"):
        metadata.MetadataProbe(settings).item_profile(candidate())
    assert not list(Path(settings["cardinal_exchange_host"]).glob("listing-*.json"))

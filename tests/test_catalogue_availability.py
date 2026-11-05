# ruff: noqa: S101
"""Unavailable titles do not starve later playable titles or relax eligibility."""

import json
from pathlib import Path

import pytest
from test_catalogue_workflow import CANDIDATE, Metadata, Slots

from src import catalogue_metadata as metadata
from src.catalogue_runner import RunnerError
from src.catalogue_store import Store
from src.catalogue_workflow import process_advanced


@pytest.mark.parametrize("outage", [False, True])
def test_unavailable_is_per_title_but_real_outage_still_breaks(tmp_path, outage):
    settings = {
        "services": {"netflix": {"region": "US"}},
        "trackers": ["HDB"],
        "media_types": ["movie"],
        "eligibility": "missing_or_free_slot",
        "daily_limit": 1,
        "max_checks_per_run": 3,
        "max_downloads_per_run": 1,
        "max_candidate_age_hours": 24,
        "timeout_seconds": 5,
        "cardinal_binary": "fixture",
    }
    store = Store(tmp_path / "state")
    for i in range(3):
        store.add({**CANDIDATE, "imdb": f"tt{1234567 + i}"})
    store.db.commit()

    class Provider(Metadata):
        calls = 0

        def item_profile(self, candidate):
            self.calls += 1
            if self.calls < 3:
                if outage:
                    raise RunnerError("Provider request failed")
                raise metadata.PlaybackUnavailableError("This exact title has no playable offer")
            return super().item_profile(candidate)

    provider = Provider()
    process_advanced(settings, store, False, metadata=provider, slots=Slots())
    states = [row[0] for row in store.db.execute("SELECT status FROM jobs ORDER BY imdb")]
    assert provider.calls == (2 if outage else 3)
    assert states == (["unknown", "unknown", "pending"] if outage else ["unavailable", "unavailable", "ready"])
    assert store.db.execute("SELECT count(*) FROM attempts").fetchone()[0] == 0
    store.db.close()


@pytest.mark.parametrize("requested,code,expected", [("123", "title_unavailable", True), ("999", "title_unavailable", False), ("123", "unknown_new_error", False)])
def test_exact_title_error_contract_only(tmp_path, monkeypatch, requested, code, expected):
    host = tmp_path / "exchange"
    settings = {
        "cardinal_exchange_host": str(host),
        "cardinal_exchange_container": "/fixture/exchange",
        "cardinal_docker": {"container": "fixture", "user": "node", "workdir": "/app/.output", "cli": "src/cli.js"},
        "timeout_seconds": 5,
    }

    def fake_download(command, _timeout):
        output = host / Path(command[command.index("--jsonoutput") + 1]).name
        output.write_text(json.dumps({"schema": 1, "cli_sha256": metadata.CLI_SHA256, "service": "netflix", "requested": requested, "error": {"code": code}}))
        return "failed"

    monkeypatch.setattr(metadata, "download", fake_download)
    candidate = {**CANDIDATE, "item": "123"}
    with pytest.raises(metadata.PlaybackUnavailableError if expected else RunnerError) as captured:
        metadata.MetadataProbe(settings).list(candidate)
    assert isinstance(captured.value, metadata.PlaybackUnavailableError) == expected

# ruff: noqa: S101
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.catalogue_prime_probe import PrimeAccessProbe, resolve_document
from src.catalogue_runner import RunnerError

GTI = "amzn1.dv.gti.66e03765-50f3-4b7e-89ed-c31e9aea7ee0"


def document(asin="B093CKHFXM", compact="0L8V88NU7CFYRKM857QDN2O5B4"):
    data = {"init": {"preparations": {"body": {"atf": {"state": {"self": {GTI: {"gti": GTI, "compactGTI": compact}}}}}, "head": {"pageMetadata": {"pageTypeId": asin}}}}}
    return '<script type="application/json">' + json.dumps(data) + "</script>"


def test_resolver_binds_only_primary_canonical_title():
    assert resolve_document(document(), "B093CKHFXM") == GTI
    assert resolve_document(document(), "0L8V88NU7CFYRKM857QDN2O5B4") == GTI
    with pytest.raises(RunnerError):
        resolve_document(document(), "B000000000")
    with pytest.raises(RunnerError):
        resolve_document('<script>{"gti":"' + GTI + '"}</script>', "B093CKHFXM")


def test_native_probe_uses_sanitized_proof_and_cleans_exchange(monkeypatch, tmp_path):
    from src import catalogue_prime_probe as module

    mount = Path("/exchange")
    exchange = tmp_path / "exchange"
    exchange.mkdir()
    settings = {"state_dir": str(tmp_path / "state"), "timeout_seconds": 120, "cardinal_docker": {"container": "fixture", "workdir": "/app/.output", "cli": "src/cli.js"}}
    probe = PrimeAccessProbe(settings)
    probe.pacer = SimpleNamespace(acquire=lambda _host: None)
    monkeypatch.setattr(module.MetadataProbe, "_install", lambda _self: (exchange, mount, "unused.cjs"))
    commands = []

    def run(command, _timeout):
        commands.append(command)
        name = Path(command[command.index("--jsonoutput") + 1]).name
        data = {
            "schema": 1,
            "cli_sha256": module.CLI_SHA256,
            "service": "amazon",
            "requested": GTI,
            "country": "GB",
            "resource": {
                "gti": GTI,
                "imdbTconst": "tt9777666",
                "actions": [
                    {
                        "metadata": {
                            "metadataActionType": "Playback",
                            "videoMaterialType": "Feature",
                            "userEntitlementMetadata": {"entitlementType": "PRIME_SUBSCRIPTION"},
                            "playbackExperienceMetadata": {"playbackEnvelope": True},
                        }
                    }
                ],
            },
        }
        (exchange / name).write_text(json.dumps(data))
        return "succeeded"

    monkeypatch.setattr(module, "download", run)
    candidate = {"service": "amazon", "item": GTI, "imdb": "tt9777666", "region": "GB"}
    assert probe.check(candidate)["state"] == "included"
    assert probe.check(candidate)["canonical_item"] == GTI and len(commands) == 1
    assert not list(exchange.glob("prime-request-*")) and not list(exchange.glob("prime-result-*"))
    assert "--listitem" in commands[0] and "--item" not in commands[0]

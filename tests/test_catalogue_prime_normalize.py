# ruff: noqa: S101, S603 -- fixed Node program and trusted repository adapter
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from src.catalogue_prime_access import classify


def test_real_native_undefined_property_is_omitted_but_cross_title_is_not():
    adapter = Path(__file__).resolve().parents[1] / "tools/cardinal-prime-access.cjs"
    source = """
const vm=require('node:vm');const isolated={exports:{}};vm.runInNewContext(process.argv[1],{require,module:isolated,exports:isolated.exports});const {normalize}=isolated.exports;
const metadata={metadataActionType:'Playback',videoMaterialType:'Feature',playbackTitle:undefined,userEntitlementMetadata:{entitlementType:'PRIME_SUBSCRIPTION',benefitType:[]},playbackExperienceMetadata:{playbackEnvelope:'secret-token'}};
const resource={gti:'amzn1.dv.gti.66e03765-50f3-4b7e-89ed-c31e9aea7ee0',imdbTconst:'tt9777666',actions:[{metadata}]};
const omitted=normalize(resource);metadata.playbackTitle='different-title';const cross=normalize(resource);
metadata.playbackTitle=undefined;metadata.userEntitlementMetadata.benefitType=['CHANNEL'];const extra=normalize(resource);
console.log(JSON.stringify({omitted,cross,extra}));
"""
    node = shutil.which("node")
    if node:
        command = [node]
    else:
        container = os.environ.get("UA_TEST_NODE_CONTAINER")
        if not container:
            pytest.skip("Node or an explicitly selected test container is required")
        docker = shutil.which("docker")
        assert docker is not None
        command = [docker, "exec", "--user", "node", container, "node"]
    result = subprocess.run([*command, "-e", source, adapter.read_text()], capture_output=True, text=True, check=True, timeout=25)
    assert "secret-token" not in result.stdout
    data = json.loads(result.stdout)
    options = {"imdb": "tt9777666", "item": "amzn1.dv.gti.66e03765-50f3-4b7e-89ed-c31e9aea7ee0", "country": "GB", "expected_country": "GB"}
    assert "playbackTitle" not in data["omitted"]["actions"][0]["metadata"]
    assert classify(data["omitted"], **options)["state"] == "included"
    assert classify(data["cross"], **options)["state"] != "included"
    assert classify(data["extra"], **options)["state"] != "included"

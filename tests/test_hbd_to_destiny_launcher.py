# ruff: noqa: S101, S603
import os
import subprocess
from pathlib import Path


def test_launcher_passes_credentials_only_via_environment_and_stdin(tmp_path):
    config = tmp_path / ".config"
    (config / "hbd").mkdir(parents=True)
    (config / "upload-assistant").mkdir()
    (config / "hbd" / "password").write_text("dummy-vps-secret\n")
    (config / "upload-assistant" / "whatbox.env").write_text(
        "UA_WHATBOX_PASSWORD='dummy-whatbox-secret'\n"
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    sshpass = fake_bin / "sshpass"
    sshpass.write_text(
        """#!/bin/bash
set -eu
[[ "$SSHPASS" == dummy-vps-secret ]]
[[ "$(</dev/stdin)" == dummy-whatbox-secret ]]
[[ "${UA_WHATBOX_PASSWORD-unset}" == unset ]]
for arg in "$@"; do [[ "$arg" != *dummy-* ]]; done
printf stub-ok
"""
    )
    sshpass.chmod(0o755)
    env = dict(os.environ, HOME=str(tmp_path), PATH=str(fake_bin) + ":" + os.environ["PATH"])
    env.pop("UA_WHATBOX_PASSWORD", None)
    launcher = Path(__file__).resolve().parents[1] / "tools" / "ua-hbd-to-destiny"
    result = subprocess.run([str(launcher)], env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert result.stdout == "stub-ok"
    assert "dummy-" not in result.stderr

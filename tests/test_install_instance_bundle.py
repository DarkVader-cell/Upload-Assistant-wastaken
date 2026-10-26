"""Exercise real bootstrap/config import with fake Docker/Git/package commands."""

# ruff: noqa: S101
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from src.config_bundle import encrypt_settings, read_config


@pytest.mark.parametrize("overwrite", [False, True])
def test_installer_imports_portable_credentials_without_network_or_client_changes(tmp_path, overwrite):
    root = Path(__file__).resolve().parents[1]
    instance = tmp_path / "instance"
    app = instance / "bootstrap"
    (app / ".git").mkdir(parents=True)
    (app / "src").symlink_to(root / "src", target_is_directory=True)
    (app / "data").mkdir()
    template = {"DEFAULT": {"screens": 0, "prowlarr_url": "", "prowlarr_api_key": ""}, "TRACKERS": {"AITHER": {"api_key": ""}}, "TORRENT_CLIENTS": {}}
    (app / "data/example_config.py").write_text("config = " + repr(template))
    (instance / "data").mkdir()
    original = {
        "DEFAULT": {"screens": 4, "local_dir": "/KEEP_LOCAL"},
        "TRACKERS": {"AITHER": {"api_key": "EXISTING_DUMMY"}},
        "TORRENT_CLIENTS": {"local": {"host": "http://LOCAL_ONLY", "local_path": "/ORIGINAL"}},
    }
    config = instance / "data/config.py"
    config.write_text("config = " + repr(original))
    config.chmod(0o600)
    bundle = tmp_path / "settings.ua-bundle"
    bundle.write_bytes(encrypt_settings({"TRACKERS": {"AITHER": {"api_key": "NEW_DUMMY", "download_dir": "/MUST_NOT_TRANSFER"}}}, "dummy-passphrase-long-enough"))
    bundle.chmod(0o600)
    key = tmp_path / "passphrase"
    key.write_text("dummy-passphrase-long-enough")
    key.chmod(0o600)
    media = tmp_path / "media"
    media.mkdir()
    fake = tmp_path / "bin"
    fake.mkdir()
    for name in ["git", "docker"]:
        path = fake / name
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o700)
    python = fake / "python3"
    python.write_text(
        '#!/bin/sh\nif [ "$1" = "-m" ] && [ "$2" = "pip" ]; then exit 0; fi\n'
        'if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then mkdir -p "$3/bin"; cp "$0" "$3/bin/python"; exit 0; fi\n'
        "exec " + shlex.quote(sys.executable) + ' "$@"\n'
    )
    python.chmod(0o700)
    args = [
        "bash",
        str(root / "scripts/install-instance.sh"),
        "--browse-root",
        str(media),
        "--install-dir",
        str(instance),
        "--import-bundle",
        str(bundle),
        "--bundle-passphrase-file",
        str(key),
        "--no-start",
    ]
    if overwrite:
        args.append("--bundle-overwrite")
    result = subprocess.run(args, capture_output=True, text=True, env={**os.environ, "PATH": str(fake) + os.pathsep + os.environ["PATH"]}, check=False)  # noqa: S603 - fixed installer, all paths isolated fixtures
    assert result.returncode == 0, result.stdout + result.stderr
    current = read_config(config)
    assert current["TRACKERS"]["AITHER"]["api_key"] == ("NEW_DUMMY" if overwrite else "EXISTING_DUMMY")
    assert "download_dir" not in current["TRACKERS"]["AITHER"]
    assert current["TORRENT_CLIENTS"] == original["TORRENT_CLIENTS"]
    assert current["DEFAULT"]["local_dir"] == "/KEEP_LOCAL"
    assert config.stat().st_mode & 0o777 == 0o600
    assert list(config.parent.glob("config.py.backup-bundle-*"))
    assert "NEW_DUMMY" not in result.stdout and "dummy-passphrase-long-enough" not in result.stdout

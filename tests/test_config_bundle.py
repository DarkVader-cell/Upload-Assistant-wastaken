"""Security and portability checks for encrypted configuration transfer."""
# ruff: noqa: S101
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from src.config_bundle import decrypt_settings, encrypt_settings, import_settings, portable_settings, read_config

PASSWORD = "a-long-test-passphrase"


def test_round_trip_and_wrong_password():
    settings = {"DEFAULT": {"prowlarr_api_key": "private-value"}}
    encrypted = encrypt_settings(settings, PASSWORD)
    assert b"private-value" not in encrypted
    assert decrypt_settings(encrypted, PASSWORD) == settings
    with pytest.raises(InvalidTag):
        decrypt_settings(encrypted, "wrong-test-passphrase")


def test_transport_excludes_machine_paths():
    settings = portable_settings({"DEFAULT": {"stats_enabled": True, "prowlarr_url": "https://example.test"}, "TORRENT_CLIENTS": {"qbit": {"local_path": ["/old"], "torrent_storage_dir": "/old", "qbit_user": "user"}}}, ["DEFAULT", "TORRENT_CLIENTS"])
    assert "stats_enabled" not in settings["DEFAULT"]
    assert settings["TORRENT_CLIENTS"]["qbit"] == {"qbit_user": "user"}


def test_import_preserves_existing_and_backups_are_private(tmp_path):
    config = tmp_path / "config.py"
    config.write_text("config = {'DEFAULT': {'prowlarr_api_key': 'existing', 'prowlarr_url': ''}}\n")
    backup = import_settings(config, {"DEFAULT": {"prowlarr_api_key": "incoming", "prowlarr_url": "https://example.test"}})
    assert read_config(config)["DEFAULT"]["prowlarr_api_key"] == "existing"
    assert read_config(config)["DEFAULT"]["prowlarr_url"] == "https://example.test"
    assert backup.stat().st_mode & 0o777 == 0o600
    assert config.stat().st_mode & 0o777 == 0o600


def test_config_does_not_execute_code(tmp_path):
    config = tmp_path / "config.py"
    marker = tmp_path / "executed"
    config.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\nconfig = {{'DEFAULT': {{}}}}")
    assert read_config(config) == {"DEFAULT": {}}
    assert not marker.exists()


def test_rejects_unknown_sections():
    with pytest.raises(ValueError):
        portable_settings({"sessions": {}}, ["sessions"])


def test_passphrase_minimum():
    with pytest.raises(ValueError):
        encrypt_settings({"DEFAULT": {}}, "short")


def test_cli_private_export_and_refuses_overwrite(tmp_path):
    config = tmp_path / "config.py"
    config.write_text("config = {'DEFAULT': {'prowlarr_api_key': 'private-value'}}")
    passphrase = tmp_path / "passphrase"
    passphrase.write_text(PASSWORD)
    passphrase.chmod(0o600)
    bundle = tmp_path / "settings.ua-bundle"
    command = [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts/config-bundle.py"), "export", "--config", str(config), "--bundle", str(bundle), "--passphrase-file", str(passphrase)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert bundle.stat().st_mode & 0o777 == 0o600
    original = bundle.read_bytes()
    assert "private-value" not in result.stdout + result.stderr
    assert subprocess.run(command, capture_output=True, check=False).returncode != 0
    assert bundle.read_bytes() == original


def test_tampered_bundle_rejected():
    encrypted = bytearray(encrypt_settings({"DEFAULT": {"prowlarr_api_key": "key"}}, PASSWORD))
    encrypted[-5] = ord("A") if encrypted[-5] != ord("A") else ord("B")
    with pytest.raises((InvalidTag, ValueError)):
        decrypt_settings(bytes(encrypted), PASSWORD)

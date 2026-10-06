"""Offline checks for installer validation and state isolation."""
# Fixed repository scripts run without user-controlled shell commands; asserts are pytest checks.
# ruff: noqa: S101, S603, S607
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install-instance.sh"


def test_installer_shell_syntax():
    result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_installer_help_requires_no_dependencies():
    result = subprocess.run(["bash", str(SCRIPT), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "--prowlarr-api-key-file" in result.stdout


def test_installer_rejects_missing_media_root():
    result = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode != 0
    assert "--browse-root is required" in result.stderr


def test_installer_rejects_unpaired_prowlarr_credentials(tmp_path):
    result = subprocess.run(
        ["bash", str(SCRIPT), "--browse-root", str(tmp_path), "--prowlarr-url", "http://localhost:9696"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "Prowlarr URL requires" in result.stderr


def test_standalone_uses_instance_state_not_checkout():
    source = SCRIPT.read_text()
    assert 'export UA_DATA_DIR="$INSTANCE_DIR"' in source
    assert 'configure_config "$app_dir" "$app_dir/.venv/bin/python" "$INSTALL_DIR"' in source
    assert 'bash "$SCRIPT_DIR/install-seedbox.sh"' in source


def test_docker_instances_do_not_claim_global_container_name():
    assert "container_name:" not in SCRIPT.read_text()

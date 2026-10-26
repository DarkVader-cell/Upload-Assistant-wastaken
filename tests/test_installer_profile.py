"""Saved one-click install profiles never carry raw credentials or payload state."""

# ruff: noqa: S101
import ast
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.config_bundle import portable_settings
from src.installer_profile import install_arguments, installation_lock, load_profile, write_launcher


def saved(tmp_path, **changes):
    media = tmp_path / "media"
    media.mkdir(exist_ok=True)
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({"version": 1, "mode": "docker", "install_dir": str(tmp_path / "instance"), "browse_root": str(media), **changes}))
    path.chmod(0o600)
    return path


def test_profile_builds_arguments_without_evaluating_shell_or_loading_secret_values(tmp_path):
    key = tmp_path / "passphrase"
    key.write_text("NEVER_IN_ARGUMENTS")
    key.chmod(0o600)
    path = saved(tmp_path, import_bundle="settings.ua-bundle", bundle_passphrase_file=str(key), bundle_overwrite=True)
    profile = load_profile(path)
    arguments = install_arguments(profile, Path("/checkout/scripts/install-instance.sh"), image="image@sha256:" + "a" * 64)
    assert "--bundle-overwrite" in arguments
    assert "NEVER_IN_ARGUMENTS" not in " ".join(arguments)
    assert arguments[arguments.index("--bundle-passphrase-file") + 1] == str(key)
    assert arguments[arguments.index("--import-bundle") + 1] == str(tmp_path / "settings.ua-bundle")


@pytest.mark.parametrize(
    "change",
    [
        {"password": "raw-secret"},
        {"api_key": "raw-secret"},
        {"start": "yes"},
        {"webui_port": True},
        {"prowlarr_url": "https://user:password@example.test"},
        {"prowlarr_url": "https://example.test/?api_key=secret"},
        {"repo_url": "http://example.test/repo"},
        {"image": "registry/user:password@host/image"},
        {"bundle_overwrite": True},
        {"browse_root": "/nonexistent-install-test-root"},
        {"install_dir": "/"},
        {"install_dir": "~"},
        {"install_dir": "bad\nInjected=thing"},
        {"revision": "latest"},
    ],
)
def test_invalid_or_secret_profiles_are_rejected(tmp_path, change):
    with pytest.raises(ValueError):
        load_profile(saved(tmp_path, **change))


def test_payload_and_state_cannot_overlap(tmp_path):
    with pytest.raises(ValueError):
        load_profile(saved(tmp_path, install_dir=str(tmp_path / "media" / "state")))
    with pytest.raises(ValueError):
        load_profile(saved(tmp_path, install_dir=str(tmp_path)))


def test_profile_permissions_and_symlink_are_checked(tmp_path):
    path = saved(tmp_path)
    path.chmod(0o666)
    with pytest.raises(ValueError):
        load_profile(path)
    path.chmod(0o600)
    link = tmp_path / "linked.json"
    link.symlink_to(path)
    with pytest.raises(ValueError):
        load_profile(link)


def test_launcher_is_private_file_references_only_and_no_overwrite(tmp_path):
    profile = saved(tmp_path)
    target = tmp_path / "Install.desktop"
    write_launcher(profile, target, Path("/checkout/scripts/one-click-install.py"))
    assert (target.stat().st_mode & 0o777) == 0o700
    assert "--apply" in target.read_text() and "Terminal=true" in target.read_text()
    assert str(profile) in target.read_text()
    with pytest.raises(ValueError):
        write_launcher(profile, target, Path("/checkout/scripts/one-click-install.py"))


def test_webui_authentication_and_host_identity_are_not_portable_credentials():
    result = portable_settings(
        {
            "DEFAULT": {"webui_api_key": "LOCAL_WEBUI_SECRET", "session_api_key": "LOCAL_SESSION", "ssh_api_key": "LOCAL_SSH_SECRET", "ptpimg_api": "SHARED_IMAGE_SECRET"},
            "TRACKERS": {"AITHER": {"api_key": "SHARED_TRACKER_SECRET", "download_dir": "/local/path"}},
        },
        ["DEFAULT", "TRACKERS"],
    )
    assert result["DEFAULT"] == {"ptpimg_api": "SHARED_IMAGE_SECRET"}
    assert result["TRACKERS"] == {"AITHER": {"api_key": "SHARED_TRACKER_SECRET"}}


def module():
    path = Path(__file__).resolve().parents[1] / "scripts/one-click-install.py"
    spec = importlib.util.spec_from_file_location("one_click_test", path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_bootstrap_scripts_keep_python311_syntax():
    root = Path(__file__).resolve().parents[1]
    for name in ["src/installer_profile.py", "scripts/one-click-install.py", "src/config_bundle.py", "scripts/config-bundle.py", "src/config_sync.py", "src/config_io.py"]:
        ast.parse((root / name).read_text(), filename=name, feature_version=(3, 11))


def test_double_clicks_cannot_run_concurrent_installers(tmp_path):
    profile = load_profile(saved(tmp_path))
    with installation_lock(profile), pytest.raises(ValueError, match="already managing"), installation_lock(profile):
        raise AssertionError("second writer should not enter")
    with installation_lock(profile):
        pass


def test_running_docker_instance_is_never_reconfigured(tmp_path, monkeypatch):
    runner = module()
    profile = load_profile(saved(tmp_path))
    root = Path(profile["install_dir"])
    root.mkdir()
    (root / "docker-compose.yml").touch()
    monkeypatch.setattr(runner, "output", lambda _args: "existing-container-id")
    with pytest.raises(ValueError, match="running"):
        runner.refuse_live_instance(profile)


def test_image_revision_and_registry_digest_are_checked(tmp_path, monkeypatch):
    runner = module()
    revision = "b" * 40
    profile = load_profile(saved(tmp_path, revision=revision))
    monkeypatch.setattr(runner.subprocess, "run", Mock())
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(
        runner,
        "output",
        lambda _args: json.dumps(
            [{"Config": {"Labels": {"org.opencontainers.image.revision": revision}}, "RepoDigests": ["ghcr.io/darkvader-cell/upload-assistant-wastaken@sha256:" + "c" * 64]}]
        ),
    )
    assert runner.pinned_image(profile).endswith("c" * 64)
    profile["revision"] = "d" * 40
    with pytest.raises(ValueError, match="revision"):
        runner.pinned_image(profile)

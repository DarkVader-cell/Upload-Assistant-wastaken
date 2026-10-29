from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_image_defaults_remain_readable_after_privilege_drop():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "chmod -R a+rX /Upload-Assistant/data /Upload-Assistant/defaults" in dockerfile


def test_local_auth_state_is_excluded_from_image():
    ignore = (ROOT / ".dockerignore").read_text().splitlines()
    assert "data/config.py" in ignore
    assert "data/webui_auth.json" in ignore
    assert "data/session_secret" in ignore


def test_local_build_and_runtime_caches_are_excluded_from_image():
    ignore = (ROOT / ".dockerignore").read_text().splitlines()
    assert {"build", "dist", "data/cache", "data/nfos"} <= set(ignore)


def test_docker_exposes_architecture_specific_mediainfo_on_path():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "Path('/usr/local/bin/mediainfo').symlink_to(binary)" in dockerfile
    workflow = (ROOT / ".github/workflows/pr-validation.yml").read_text()
    assert 'test -x "$(command -v mediainfo)"' in workflow
    assert "test -x /Upload-Assistant/bin/MI/linux/mediainfo" not in workflow


def test_docker_installs_strict_healthcheck():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "COPY scripts/docker-healthcheck.py /usr/local/bin/upload-assistant-healthcheck" in dockerfile
    assert 'CMD ["python", "/usr/local/bin/upload-assistant-healthcheck"]' in dockerfile

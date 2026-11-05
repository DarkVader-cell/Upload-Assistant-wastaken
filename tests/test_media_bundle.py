# ruff: noqa: S101
"""The standalone archive works without the repo or any catalogue configuration."""

import ast
import os
import runpy
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_standalone_python311_grammar():
    for name in [
        "src/catalogue_media.py",
        "src/media_naming.py",
        "src/media_privacy.py",
        "src/media_template.py",
        "src/media_selection.py",
        "src/media_output.py",
        "tools/catalogue-media.py",
        "tools/media-release.py",
        "tools/build-media-release.py",
    ]:
        ast.parse((ROOT / name).read_text(), filename=name, feature_version=(3, 11))


def test_zipapp_is_self_contained_and_has_no_config_or_secrets(tmp_path):
    archive = tmp_path / "media-release.pyz"
    build = runpy.run_path(str(ROOT / "tools/build-media-release.py"))
    assert build["main"](["--output", str(archive)]) == 0
    with zipfile.ZipFile(archive) as bundle:
        names = {name for name in bundle.namelist() if not name.endswith("/")}
        assert names == {
            "__main__.py",
            "media_release_cli.py",
            "src/__init__.py",
            "src/catalogue_media.py",
            "src/media_naming.py",
            "src/media_privacy.py",
            "src/media_template.py",
            "src/media_selection.py",
            "src/media_output.py",
        }
    result = subprocess.run(  # noqa: S603 -- fixed Python and an archive built by this test
        [sys.executable, str(archive), "--help"], cwd=tmp_path, env={**os.environ, "PYTHONPATH": ""}, capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 0 and "--output-dir" in result.stdout and "--allow-linked-input" in result.stdout

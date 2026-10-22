"""Test persistent operation completion without launching remote processes."""
# ruff: noqa: S101
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src import remote_upload_worker


@pytest.mark.parametrize('code, expected', [(0, 'completed'), (1, 'needs_review')])
def test_worker_persists_result(tmp_path, monkeypatch, code, expected):
    record = tmp_path / 'op.json'
    record.write_text(json.dumps({'id': 'dummy', 'state': 'queued'}))
    monkeypatch.setattr('sys.argv', ['worker', str(record), '/private/config.json', 'tick'])
    run = Mock(return_value=SimpleNamespace(returncode=code))
    monkeypatch.setattr(remote_upload_worker.subprocess, 'run', run)
    remote_upload_worker.main()
    assert json.loads(record.read_text())['state'] == expected
    assert record.stat().st_mode & 0o777 == 0o600


def test_installer_quotes_systemd_and_rejects_newline():
    spec = importlib.util.spec_from_file_location('timer_installer', Path(__file__).resolve().parents[1] / 'scripts/install-remote-upload-timer.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.quote('/a b/%x') == '"/a b/%%x"'
    with pytest.raises(ValueError):
        module.quote('/bad\nExecStart=bad')

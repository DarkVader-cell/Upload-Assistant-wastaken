"""No SSH processes or tracker operations are executed in these tests."""
# ruff: noqa: S101
import json
from unittest.mock import Mock

import pytest
from flask import Flask

from web_ui.remote_upload import create_blueprint


@pytest.fixture
def context(tmp_path, monkeypatch):
    root = tmp_path / 'media'
    root.mkdir()
    (root / 'test.mkv').write_bytes(b'dummy')
    config = tmp_path / 'backend.json'
    config.write_text(json.dumps({'state_dir': str(tmp_path / 'state'), 'ssh_key': '/dummy/key', 'source_roots': [str(root)]}))
    registry = tmp_path / 'backends.json'
    registry.write_text(json.dumps({'nvme': str(config)}))
    monkeypatch.setenv('UA_REMOTE_UPLOAD_BACKENDS', str(registry))
    launch = Mock()
    monkeypatch.setattr('web_ui.remote_upload.subprocess.Popen', launch)
    flags = {'auth': True, 'csrf': True, 'origin': True}
    app = Flask(__name__)
    app.register_blueprint(create_blueprint(authenticated=lambda: flags['auth'], csrf_valid=lambda: flags['csrf'], same_origin=lambda: flags['origin'], csrf_token=lambda: 'dummy'))
    return app.test_client(), flags, launch, root


def test_auth_and_csrf(context):
    client, flags, launch, _ = context
    flags['auth'] = False
    assert client.get('/api/remote-upload').status_code == 401
    flags['auth'] = True
    flags['csrf'] = False
    assert client.post('/api/remote-upload', json={}).status_code == 403
    flags['csrf'] = True
    flags['origin'] = False
    assert client.post('/api/remote-upload', json={}).status_code == 403
    launch.assert_not_called()


def test_submit_and_prevent_duplicate_workers(context):
    client, _, launch, root = context
    data = {'backend': 'nvme', 'action': 'execute', 'source': str(root / 'test.mkv'), 'trackers': ['PTP'], 'return_after': 0}
    assert client.post('/api/remote-upload', json=data).status_code == 202
    assert launch.call_count == 1
    assert client.post('/api/remote-upload', json=data).status_code == 409
    assert launch.call_count == 1
    result = client.get('/api/remote-upload').get_json()
    assert 'ssh_key' not in json.dumps(result)
    assert result['backends']['nvme']['operations'][0]['state'] == 'queued'


@pytest.mark.parametrize('changes', [{'source': '/etc/passwd'}, {'backend': '../../backend.json'}, {'trackers': ['PTP;echo']}, {'return_after': -1}, {'return_after': 'nan'}, {'action': 'delete'}])
def test_invalid_submission(context, changes):
    client, _, launch, root = context
    data = {'backend': 'nvme', 'action': 'execute', 'source': str(root / 'test.mkv'), 'trackers': ['PTP']}
    data.update(changes)
    assert client.post('/api/remote-upload', json=data).status_code == 400
    launch.assert_not_called()

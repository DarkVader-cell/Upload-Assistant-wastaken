"""Control API regression without real processes, signals or network."""
# ruff: noqa: S101
import json
from unittest.mock import Mock

from flask import Flask

import web_ui.remote_upload as api


def test_controls_resolve_only_recorded_stage_and_keep_csrf(tmp_path,monkeypatch):
    state=tmp_path/'state'
    state.mkdir()
    id_='a'*32
    (state/'ledger.json').write_text(json.dumps({'stages':{id_:{'id':id_,'state':'copying'}}}))
    config=tmp_path/'backend.json'
    config.write_text(json.dumps({'state_dir':str(state)}))
    monkeypatch.setattr(api,'backends',lambda:{'dummy':config})
    control=Mock(return_value={'state':'paused'})
    monkeypatch.setattr(api,'control_transfer',control)
    flags={'csrf':True}
    app=Flask(__name__)
    app.register_blueprint(api.create_blueprint(authenticated=lambda:True,csrf_valid=lambda:flags['csrf'],same_origin=lambda:True,csrf_token=lambda:'dummy'))
    client=app.test_client()
    response=client.post('/api/remote-upload/control',json={'backend':'dummy','stage':id_,'action':'pause','pid':999})
    assert response.status_code==200
    assert control.call_args.args[1]=={'id':id_,'state':'copying'}
    assert client.post('/api/remote-upload/control',json={'backend':'dummy','stage':'unknown','action':'cancel'}).status_code==409
    assert control.call_count==1
    flags['csrf']=False
    assert client.post('/api/remote-upload/control',json={'backend':'dummy','stage':id_,'action':'cancel'}).status_code==403
    assert control.call_count==1

"""Remote command construction only; no SSH or tracker requests."""
# ruff: noqa: S101
import json
from types import SimpleNamespace
from unittest.mock import Mock

from src import remote_upload


def test_remote_command_inherits_terminal_and_prompt_environment():
    cfg={'remote':{'host':'192.0.2.1','user':'dummy','port':22},'known_hosts':'/dummy/hosts','ssh_key':'/dummy/key','remote_ua_command':['/dummy/python','/dummy/upload.py']}
    controller=SimpleNamespace(cfg=cfg,save=Mock(),ledger={'stages':{'stage':{'id':'stage','state':'ready','remote_input':'/nvme/source.mkv'}}},peer=SimpleNamespace(qb=Mock()))
    engine=SimpleNamespace(qb_pages=Mock(side_effect=[[],[]]))
    jobs=remote_upload.Jobs(controller,engine)
    jobs.jobs['job']={'state':'staged','stage':'stage','delay':3600,'torrents':{}}
    runner=Mock()
    jobs.run('job',['PASSTHEPOPCORN'],runner,webui=True,arguments=['--edition','Extended Edition'])
    argv=runner.call_args.args[0]
    assert '-T' in argv and '-tt' not in argv
    assert 'UA_WEBUI_PROGRESS_STDOUT=1' in argv[-1]
    assert 'UA_WEBUI_PROMPT_SOUND_STDOUT=1' in argv[-1]
    assert '--unattended' not in argv[-1]
    assert 'Extended Edition' in argv[-1]
    # No redirected pipes/DEVNULL: the existing session owns stdin/stdout/stderr.
    assert runner.call_args.kwargs=={'check':True}


def test_webui_entry_stages_then_runs_interactive_without_real_network(tmp_path,monkeypatch):
    source=tmp_path/'source.mkv'
    source.write_bytes(b'dummy')
    cfg=tmp_path/'config.json'
    cfg.write_text(json.dumps({'role':'dedi','ssh_key':'/dummy/key','source_roots':[str(tmp_path)]}))
    registry=tmp_path/'backends.json'
    registry.write_text(json.dumps({'dummy':str(cfg)}))
    monkeypatch.setenv('UA_REMOTE_UPLOAD_BACKENDS',str(registry))
    peer=SimpleNamespace(sftp=SimpleNamespace(close=Mock()),ssh=SimpleNamespace(close=Mock()))
    controller=object()
    monkeypatch.setattr(remote_upload,'load_engine',lambda:SimpleNamespace(Peer=lambda _cfg:peer,Controller=lambda _cfg,_peer:controller))
    stage=Mock(return_value='job')
    run=Mock()
    monkeypatch.setattr(remote_upload,'Jobs',lambda _controller,_engine:SimpleNamespace(stage=stage,run=run))
    remote_upload.webui_entry([str(source),'--remote-backend','dummy','--remote-return-after','3600','-tk','PASSTHEPOPCORN','--edition','Extended Edition'])
    stage.assert_called_once_with(source,3600)
    run.assert_called_once_with('job',['PASSTHEPOPCORN'],arguments=['--edition','Extended Edition'],webui=True)
    peer.ssh.close.assert_called_once()

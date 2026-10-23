"""Reuse and no-extra-hash mode without SSH, tracker uploads or real payloads."""
# ruff: noqa: S101
import hashlib
from types import SimpleNamespace
from unittest.mock import Mock

import bencodepy
import pytest

from src.remote_upload import Jobs, load_engine
from web_ui.remote_upload import remote_options, stage_projection


def test_commit_can_skip_extra_sha_scan_but_keeps_file_checks(tmp_path,monkeypatch):
    s=load_engine()
    id_='a'*32
    root=tmp_path/'ssd'
    payload=root/'stages'/id_/'payload'
    payload.mkdir(parents=True)
    (payload/'dummy.bin').write_bytes(b'data')
    scan=Mock(side_effect=AssertionError('Unexpected extra SHA scan'))
    monkeypatch.setattr(s,'sha_file',scan)
    record={'id':id_,'verify_stage_sha256':False,'files':[{'relative':'dummy.bin','size':4,'sha256':None}]}
    assert s.rpc({'stage_root':str(root)},{'action':'commit','record':record}) is True
    scan.assert_not_called()
    record['files'][0]['size']=5
    with pytest.raises(s.RefuseError):
        s.rpc({'stage_root':str(root)},{'action':'commit','record':record})


def test_seed_mode_still_requires_exact_piece_proof_without_cached_sha(tmp_path):
    s=load_engine()
    file=tmp_path/'dummy.bin'
    file.write_bytes(b'data')
    raw=bencodepy.encode({b'info':{b'name':b'dummy.bin',b'length':4,b'piece length':16384,b'pieces':hashlib.sha1(b'data',usedforsecurity=False).digest()}})
    hashes=[]
    assert s.verify_pieces(raw,[file],[None],sha256_out=hashes)
    assert hashes==[hashlib.sha256(b'data').hexdigest()]
    file.write_bytes(b'bad!')
    with pytest.raises(s.RefuseError):
        s.verify_pieces(raw,[file],[None])


def test_reuse_ready_stage_does_not_recopy_and_refuses_changed_original(tmp_path):
    engine=load_engine()
    file=tmp_path/'dummy.mkv'
    file.write_bytes(b'data')
    id_='b'*32
    stage={'id':id_,'state':'ready','source':str(file),'remote_input':'/ssd/payload/dummy.mkv','writer_pid':999999999,'writer_start':'gone','files':[{'source':str(file),'relative':'dummy.mkv','size':4,'fingerprint':engine.fingerprint(file)}]}
    peer=SimpleNamespace(rpc=Mock(return_value=[{'origin':[id_,'dummy.mkv'],'size':4}]))
    controller=SimpleNamespace(ledger={'stages':{id_:stage}},save=Mock(),peer=peer,stage=Mock(side_effect=AssertionError('Must not copy')))
    jobs=Jobs(controller,engine)
    attempt=jobs.reuse_stage(id_,file,3600)
    assert jobs.jobs[attempt]['reused'] is True
    controller.stage.assert_not_called()
    peer.rpc.assert_called_once_with('inspect',paths=['/ssd/payload/dummy.mkv'])
    file.write_bytes(b'changed')
    with pytest.raises(ValueError,match='Original changed'):
        jobs.reuse_stage(id_,file,3600)


def test_reuse_projection_and_internal_option_validation(tmp_path):
    id_='c'*32
    stage={'id':id_,'state':'ready','source':'/dummy/source.mkv','writer_pid':999999999,'writer_start':'gone'}
    jobs={'failed':{'stage':id_,'state':'needs_review','trackers':['PASSTHEPOPCORN'],'delay':3600,'arguments':['--edition','Extended Edition']}}
    view=stage_projection(tmp_path,stage,jobs)
    assert view['can_reuse']
    assert '--remote-stage' in view['resume_args']
    assert remote_options(view['resume_args'],allow_stage=True)==['--edition','Extended Edition']
    with pytest.raises(ValueError):
        remote_options('--remote-stage ../../bad',allow_stage=True)
    jobs['failed']['state']='uploading'
    assert not stage_projection(tmp_path,stage,jobs)['can_reuse']

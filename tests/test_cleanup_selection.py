"""Selected cleanup scope and equivalent proof reuse, with synthetic data only."""
# ruff: noqa: S101
import hashlib
import os
from unittest.mock import Mock

import bencodepy
import pytest

from src.remote_upload import load_engine


def prepare(tmp_path,monkeypatch,change=False):
    s=load_engine()
    payload=tmp_path/'dedi'
    payload.mkdir()
    file=payload/'dummy.bin'
    file.write_bytes(b'dummy data')
    raws={}
    for tracker in (b'A',b'B'):
        info={b'name':b'dummy.bin',b'length':10,b'piece length':16384,b'pieces':hashlib.sha1(b'dummy data',usedforsecurity=False).digest(),b'source':tracker}
        h=hashlib.sha1(bencodepy.encode(info),usedforsecurity=False).hexdigest()
        raws[h]=bencodepy.encode({b'info':info})
    info={'save_path':str(payload),'progress':1,'amount_left':0,'state':'uploading'}
    second=list(raws)[1]
    class Target:
        def info(self,h):
            assert h in raws,'Unselected registration must not be queried'
            return info
        def call(self,path,args=None,**_kwargs):
            assert path=='torrents/export'
            if change and args['hash']==second:
                stat=file.stat()
                os.utime(file,ns=(stat.st_atime_ns,stat.st_mtime_ns+1000000))
            return raws[args['hash']]
    monkeypatch.setattr(s,'QB',lambda _cfg:Target())
    peer=Mock()
    peer.rpc.return_value={'removed_files':3}
    c=s.Controller({'state_dir':str(tmp_path/'state')},peer)
    a,b,d='a'*32,'b'*32,'d'*32
    c.ledger['stages']={a:{'state':'ready','files':[]},b:{'state':'ready','files':[]},d:{'state':'ready','files':[]}}
    for h in raws:
        c.ledger['returns'][h]={'state':'returned','origins':[{'path':'/ssd/'+h,'inode':[1,2],'origin':[a,'dummy.bin']}]}
    c.ledger['returns']['b'*40]={'state':'returned','origins':[{'origin':[b,'other.bin']}]}
    c.ledger['returns']['c'*40]={'state':'needs_review','origins':[{'origin':[d,'failed.bin']}]}
    spy=Mock(wraps=s.verify_pieces)
    monkeypatch.setattr(s,'verify_pieces',spy)
    return s,c,peer,spy,file,a,b,d


def test_cleanup_is_scoped_and_identical_piece_proofs_are_read_once(tmp_path,monkeypatch):
    _s,c,peer,spy,file,a,b,d=prepare(tmp_path,monkeypatch)
    c.cleanup(confirmed=True,stage_ids=[a])
    assert spy.call_count==1
    assert peer.rpc.call_args.kwargs['stages']==[a]
    assert c.ledger['stages'][a]['state']=='cleaned'
    assert c.ledger['stages'][b]['state']=='ready'
    assert c.ledger['stages'][d]['state']=='ready'
    assert c.ledger['returns']['b'*40]['state']=='returned'
    assert c.ledger['returns']['c'*40]['state']=='needs_review'
    assert file.read_bytes()==b'dummy data'


def test_related_failure_blocks_every_deletion(tmp_path,monkeypatch):
    s,c,peer,_spy,_file,a,_b,_d=prepare(tmp_path,monkeypatch)
    c.ledger['returns']['c'*40]['origins']=[{'origin':[a,'failed.bin']}]
    with pytest.raises(s.RefuseError,match='unresolved'):
        c.cleanup(confirmed=True,stage_ids=[a])
    peer.rpc.assert_not_called()


def test_changed_dedi_payload_aborts_before_remote_cleanup(tmp_path,monkeypatch):
    s,c,peer,_spy,_file,a,_b,_d=prepare(tmp_path,monkeypatch,change=True)
    with pytest.raises(s.RefuseError,match='changed'):
        c.cleanup(confirmed=True,stage_ids=[a])
    peer.rpc.assert_not_called()

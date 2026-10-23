"""Native protocol and partial removal tested only against generated dummy files."""
# ruff: noqa: S101
import hashlib
import io
import shutil
import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.remote_upload import load_engine


@pytest.fixture
def engine():
    return load_engine()


def test_native_transfer_parameters_and_progress(engine,tmp_path,monkeypatch):
    class Input(io.BytesIO):
        def close(self):
            pass
    class Process:
        def __init__(self):
            self.stdin=Input()
            self.stdout=tempfile.TemporaryFile()  # noqa: SIM115 -- closed by fake process context manager
            self.stdout.write(b'\r 512 50% 10.00MB/s 0:00:01\r 1,024 100% 10.00MB/s 0:00:00\n')
            self.stdout.seek(0)
        def __enter__(self):
            return self
        def __exit__(self,*_args):
            self.stdout.close()
        def wait(self):
            return 0
    process=Process()
    popen=Mock(return_value=process)
    monkeypatch.setattr(engine.subprocess,'Popen',popen)
    cfg={'remote':{'host':'192.0.2.1','user':'dummy','port':6969},'ssh_key':'/dummy/key','known_hosts':'/dummy/hosts'}
    progress=[]
    engine.native_transfer(cfg,tmp_path,'/dummy/stage',[{'relative':'film with spaces.mkv'}],progress.append)
    argv=popen.call_args.args[0]
    assert argv[0]=='/usr/bin/rsync'
    assert '--whole-file' in argv and '--inplace' in argv and '--no-compress' in argv
    assert not any(arg.startswith('--delete') for arg in argv)
    ssh=next(arg for arg in argv if arg.startswith('--rsh='))
    assert 'StrictHostKeyChecking=yes' in ssh and 'Compression=no' in ssh and '-4' in ssh
    assert process.stdin.getvalue()==b'film with spaces.mkv\0'
    assert progress==[512,1024]


@pytest.mark.parametrize('verify', [True, False])
def test_native_staging_respects_optional_sha_mode(engine,tmp_path,monkeypatch,verify):
    source=tmp_path/'original.mkv'
    source.write_bytes(b'dummy payload')
    payload=tmp_path/'ssd'/'payload'
    cfg={'state_dir':str(tmp_path/'state'),'source_roots':[str(tmp_path)],'transfer_protocol':'rsync','ssh_key':'/dummy/key','reserve_bytes':0}
    if not verify:
        cfg['verify_stage_sha256']=False
        monkeypatch.setattr(engine,'sha_file',Mock(side_effect=AssertionError('No extra source scan allowed')))
    class Peer:
        def rpc(self,action,**fields):
            if action=='space':
                return {'free':1000000}
            if action=='prepare':
                payload.mkdir(parents=True)
                return str(payload)
            if action=='capabilities':
                return {'rsync':True}
            if action=='commit':
                f=fields['record']['files'][0]
                if verify:
                    assert hashlib.sha256((payload/f['relative']).read_bytes()).hexdigest()==f['sha256']
                else:
                    assert f['sha256'] is None
                    assert fields['record']['verify_stage_sha256'] is False
                return True
            raise AssertionError(action)
    def transfer(_cfg,parent,target,files,progress):
        for file in files:
            shutil.copyfile(parent/file['relative'],Path(target)/file['relative'])
        progress(sum(file['size'] for file in files))
    monkeypatch.setattr(engine,'native_transfer',transfer)
    monkeypatch.setattr(engine.shutil,'which',lambda _name:'/dummy/rsync')
    c=engine.Controller(cfg,Peer())
    c.stage(source)
    r=next(iter(c.ledger['stages'].values()))
    assert r['state']=='ready' and r['bytes_sent']==len(b'dummy payload')
    assert source.read_bytes()==b'dummy payload'


@pytest.mark.parametrize('unsafe',['unknown','hardlink','referenced','symlink'])
def test_partial_cleanup_refuses_unknown_or_referenced_files(engine,tmp_path,monkeypatch,unsafe):
    id_='a'*32
    root=tmp_path/'ssd'
    payload=root/'stages'/id_/'payload'
    payload.mkdir(parents=True)
    file=payload/'dummy.bin'
    file.write_bytes(b'partial')
    refs=[]
    if unsafe=='unknown':
        (payload/'unrecorded.bin').write_bytes(b'keep')
    if unsafe=='hardlink':
        (tmp_path/'other').hardlink_to(file)
    if unsafe=='referenced':
        refs=[{'content_path':str(file)}]
    if unsafe=='symlink':
        (payload/'link').symlink_to(file)
    monkeypatch.setattr(engine,'QB',lambda _cfg:object())
    monkeypatch.setattr(engine,'qb_pages',lambda _qb:refs)
    original_glob=Path.glob
    monkeypatch.setattr(Path,'glob',lambda p,pattern,**kw:iter(()) if p==Path('/proc') else original_glob(p,pattern,**kw))
    with pytest.raises(engine.RefuseError):
        engine.rpc({'stage_root':str(root)},{'action':'discard_partial','record':{'id':id_,'files':[{'relative':'dummy.bin','size':100}]}})
    assert file.read_bytes()==b'partial'


def test_partial_cleanup_removes_only_recorded_remote_copy(engine,tmp_path,monkeypatch):
    id_='b'*32
    root=tmp_path/'ssd'
    directory=root/'stages'/id_
    payload=directory/'payload'
    payload.mkdir(parents=True)
    (payload/'dummy.bin').write_bytes(b'partial')
    original=tmp_path/'dedicated-original.bin'
    original.write_bytes(b'original untouched')
    (directory/'record.json').write_text('{}')
    monkeypatch.setattr(engine,'QB',lambda _cfg:object())
    monkeypatch.setattr(engine,'qb_pages',lambda _qb:[])
    original_glob=Path.glob
    monkeypatch.setattr(Path,'glob',lambda p,pattern,**kw:iter(()) if p==Path('/proc') else original_glob(p,pattern,**kw))
    result=engine.rpc({'stage_root':str(root)},{'action':'discard_partial','record':{'id':id_,'files':[{'relative':'dummy.bin','size':100}]}})
    assert result=={'removed_files':1}
    assert not payload.exists()
    assert original.read_bytes()==b'original untouched'
    assert (directory/'record.json').exists()

"""Deletion preflight tested only with generated hardlinks and fake qB inventories."""
# ruff: noqa: S101
import hashlib
import json
from pathlib import Path

import pytest

from src.remote_upload import load_engine


def fixture(tmp_path,monkeypatch):
    engine=load_engine()
    id_='a'*32
    root=tmp_path/'ssd'
    stage=root/'stages'/id_
    payload=stage/'payload'
    payload.mkdir(parents=True)
    raw=payload/'dummy.bin'
    raw.write_bytes(b'payload')
    links=[]
    for tracker in ('A','B'):
        path=root/'Uploads'/tracker/'dummy.bin'
        path.parent.mkdir(parents=True)
        path.hardlink_to(raw)
        stat=path.stat()
        links.append({'path':str(path),'inode':[stat.st_dev,stat.st_ino],'origin':[id_,'dummy.bin']})
    (stage/'record.json').write_text(json.dumps({'id':id_,'files':[{'relative':'dummy.bin','sha256':hashlib.sha256(b'payload').hexdigest()}]}))
    monkeypatch.setattr(engine,'QB',lambda _cfg:object())
    monkeypatch.setattr(engine,'qb_pages',lambda _qb:[])
    glob=Path.glob
    monkeypatch.setattr(Path,'glob',lambda p,pattern,**kw:iter(()) if p==Path('/proc') else glob(p,pattern,**kw))
    return engine,root,raw,links,{'action':'clean','links':links,'stages':[id_],'stage_checksums':{id_:{'dummy.bin':hashlib.sha256(b'payload').hexdigest()}}}


@pytest.mark.parametrize('duplicate',[False,True])
def test_success_removes_exact_link_set_and_preserves_original_and_audit(tmp_path,monkeypatch,duplicate):
    engine,root,raw,links,request=fixture(tmp_path,monkeypatch)
    if duplicate:
        request['links']=[*links,links[0]]
    original=tmp_path/'dedicated-original.bin'
    original.write_bytes(b'payload')
    result=engine.rpc({'stage_root':str(root)},request)
    assert result['removed_files']==3
    assert result['removed_bytes']==len(b'payload')
    assert not raw.exists()
    assert all(not Path(link['path']).exists() for link in links)
    assert original.read_bytes()==b'payload'
    assert (raw.parent.parent/'record.json').exists()


@pytest.mark.parametrize('block',['unknown_link','live_reference','unknown_file','missing_reference_fields'])
def test_whole_batch_preflight_blocks_without_partial_deletion(tmp_path,monkeypatch,block):
    engine,root,raw,links,request=fixture(tmp_path,monkeypatch)
    if block=='unknown_link':
        (root/'unreturned.bin').hardlink_to(raw)
    if block=='live_reference':
        monkeypatch.setattr(engine,'qb_pages',lambda _qb:[{'content_path':links[1]['path']}])
    if block=='unknown_file':
        (raw.parent/'unknown.bin').write_bytes(b'keep')
    if block=='missing_reference_fields':
        monkeypatch.setattr(engine,'qb_pages',lambda _qb:[{}])
    with pytest.raises(engine.RefuseError):
        engine.rpc({'stage_root':str(root)},request)
    assert raw.read_bytes()==b'payload'
    assert all(Path(link['path']).exists() for link in links)

"""No post-copy SHA pass: cleanup still needs independently obtained proof."""
# ruff: noqa: S101
import hashlib
import json
from pathlib import Path

import pytest

from src.remote_upload import load_engine


def test_stage_cleanup_without_cached_sha_needs_return_proof(tmp_path,monkeypatch):
    s=load_engine()
    id_='d'*32
    root=tmp_path/'ssd'
    stage=root/'stages'/id_
    payload=stage/'payload'
    payload.mkdir(parents=True)
    file=payload/'dummy.bin'
    file.write_bytes(b'data')
    (stage/'record.json').write_text(json.dumps({'id':id_,'files':[{'relative':'dummy.bin','sha256':None}]}))
    monkeypatch.setattr(s,'QB',lambda _cfg:object())
    monkeypatch.setattr(s,'qb_pages',lambda _qb:[])
    glob=Path.glob
    monkeypatch.setattr(Path,'glob',lambda p,pattern,**kw:iter(()) if p==Path('/proc') else glob(p,pattern,**kw))
    request={'action':'clean','links':[],'stages':[id_]}
    with pytest.raises(s.RefuseError,match='checksum proof'):
        s.rpc({'stage_root':str(root)},request)
    assert file.read_bytes()==b'data'
    request['stage_checksums']={id_:{'dummy.bin':hashlib.sha256(b'data').hexdigest()}}
    assert s.rpc({'stage_root':str(root)},request)['removed_files']==1
    assert not file.exists()
    assert (stage/'record.json').exists()

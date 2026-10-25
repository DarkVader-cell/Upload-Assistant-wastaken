"""Known site ACKs recover the client before new-upload/dupe/report gates."""
# ruff: noqa: S101
import asyncio
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import bencodepy

from src.meta import Meta
from src.runtime.submission_progress import SubmissionJournal
from src.trackerhandle import resume_acknowledged_clients


def acknowledged(tmp_path):
    source = tmp_path/'movie.mkv'
    source.write_bytes(b'dummy')
    meta = Meta(base_dir=str(tmp_path),path=str(source),uuid=source.name,filelist=[str(source)],
                category='MOVIE',name='Movie',trackers=['AITHER'],imghost='ptscreens')
    target = tmp_path/'tmp'/meta.uuid/'[AITHER].torrent'
    target.parent.mkdir(parents=True)
    target.write_bytes(bencodepy.encode({b'info':{b'name':b'movie.mkv',b'length':5,b'piece length':16384,
        b'pieces':hashlib.sha1(b'dummy',usedforsecurity=False).digest(),b'private':1}}))
    journal = SubmissionJournal.for_meta(meta)
    journal.begin('AITHER')
    journal.acknowledge('AITHER',meta)
    meta.tracker_status = {'AITHER':{'upload':False,'dupe':True}}
    return meta,journal


def test_known_ack_recovers_client_without_new_upload_permission(tmp_path):
    meta,journal = acknowledged(tmp_path)
    client = SimpleNamespace(add_to_client=AsyncMock())
    # Losing the redundant cache copy is harmless if the work artifact still
    # matches the ACK's recorded cryptographic digest exactly.
    (journal.directory/journal.lookup('AITHER')['torrent']).unlink()
    assert asyncio.run(resume_acknowledged_clients(meta,client)) == {'AITHER'}
    client.add_to_client.assert_awaited_once_with(meta,'AITHER')
    assert meta.tracker_status['AITHER']['upload'] is False
    assert meta.tracker_status['AITHER']['upload_success'] is True


def test_all_acknowledged_pipeline_does_not_reenter_slot_or_report_flows(tmp_path,monkeypatch):
    import upload
    meta,_journal = acknowledged(tmp_path)
    client = SimpleNamespace(add_to_client=AsyncMock())
    monkeypatch.setattr(upload,'config',{'DEFAULT':{}})
    monkeypatch.setattr(upload,'client',client,raising=False)
    monkeypatch.setattr(upload,'Prep',lambda **_kwargs:object())
    monkeypatch.setattr('src.runtime.prepared_stage.gather_with_resume',AsyncMock(return_value=meta))
    monkeypatch.setattr(upload,'Args',lambda _cfg:object())
    monkeypatch.setattr(upload,'UploadHelper',lambda _cfg:object())
    monkeypatch.setattr(upload,'TrackerSetup',lambda **_kwargs:SimpleNamespace(filter_unsupported_trackers=lambda _meta:None))
    monkeypatch.setattr(upload,'name_manager',SimpleNamespace(get_name=AsyncMock(return_value=('Movie','Movie','Movie',[]))),raising=False)
    monkeypatch.setattr(upload,'write_meta_file',AsyncMock())
    def forbidden(**_kwargs):
        raise AssertionError('Already-ACKed sites must not enter new-upload eligibility/reporting')
    monkeypatch.setattr(upload,'TrackerStatusManager',forbidden)
    assert asyncio.run(upload.process_meta(meta,str(tmp_path))) is True
    assert meta.trackers == [] and meta.we_are_uploading is False
    client.add_to_client.assert_awaited_once()
    assert meta.tracker_status['AITHER']['upload'] is False


def test_partial_failure_is_not_marked_as_a_finished_queue_item():
    from upload import queue_item_has_successful_upload
    assert not queue_item_has_successful_upload([{'upload_success':True},{'upload':True,'upload_success':False}])
    assert not queue_item_has_successful_upload([{'upload_success':True,'needs_review':True}])
    assert queue_item_has_successful_upload([{'upload_success':True},{'upload':False,'skipped':True}])

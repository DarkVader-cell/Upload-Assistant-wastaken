"""SQLite contention never permits a second tracker POST or loses an ACK."""
# ruff: noqa: S101
import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from src.meta import Meta
from src.runtime.submission_progress import SubmissionJournal


def test_legacy_receipts_survive_wal_migration(tmp_path):
    path=tmp_path/'submissions.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE submissions (tracker TEXT PRIMARY KEY, state TEXT, owner TEXT, torrent TEXT, digest TEXT, status TEXT, nonce TEXT)')
        db.execute('INSERT INTO submissions VALUES (?, ?, ?, NULL, NULL, ?, ?)',('AITHER','acknowledged','dead','{"torrent_id":42}','old-review-token'))
    journal=SubmissionJournal(tmp_path)
    assert journal.lookup('AITHER')['status']=='{"torrent_id":42}'
    assert journal.lookup('AITHER')['nonce']=='old-review-token'
    assert journal.begin('AITHER') is False
    with journal.connect() as db:
        assert db.execute('PRAGMA journal_mode').fetchone()[0]=='wal'
        assert db.execute('PRAGMA synchronous').fetchone()[0]==2


def test_live_reader_cannot_block_ack_commit(tmp_path):
    journal=SubmissionJournal(tmp_path)
    journal.begin('AITHER')
    reader=sqlite3.connect(journal.path)
    reader.execute('BEGIN')
    reader.execute('SELECT * FROM submissions').fetchall()
    executor=ThreadPoolExecutor(max_workers=1)
    meta=SimpleNamespace(tracker_status={},base_dir=str(tmp_path),uuid='work')
    try:
        future=executor.submit(journal.acknowledge,'AITHER',meta)
        future.result(timeout=2)
    finally:
        reader.rollback()
        reader.close()
        executor.shutdown(wait=True)
    assert journal.lookup('AITHER')['state']=='acknowledged'


def test_parallel_tracker_receipts_and_reopened_instances(tmp_path):
    first=SubmissionJournal(tmp_path)
    meta=SimpleNamespace(tracker_status={},base_dir=str(tmp_path),uuid='work')
    def record(index):
        journal=SubmissionJournal(tmp_path)
        tracker=f'TEST_{index}'
        assert journal.begin(tracker)
        journal.acknowledge(tracker,meta)
        assert journal.lookup(tracker)['state']=='acknowledged'
    with ThreadPoolExecutor(max_workers=16) as executor:
        list(executor.map(record,range(40)))
    for index in range(40):
        assert first.begin(f'TEST_{index}') is False


@pytest.mark.parametrize('phase',['begin','acknowledge'])
def test_busy_errors_are_reported_without_replaying_post(tmp_path,monkeypatch,phase):
    import src.trackerhandle as handle
    source=tmp_path/'movie.mkv'
    source.write_bytes(b'dummy')
    meta=Meta(base_dir=str(tmp_path),path=str(source),uuid=source.name,filelist=[str(source)],
              category='MOVIE',name='Movie',trackers=['AITHER'],tracker_status={'AITHER':{'upload':True}})
    posts=[]
    class Setup:
        def __init__(self,**_kwargs):pass
        def trackers_enabled(self,_meta):return ['AITHER']
    class Tracker:
        tracker='AITHER'
        def __init__(self,**_kwargs):pass
        async def upload(self,_meta):
            posts.append('POST')
            return True
    class Client:
        async def add_to_client(self,*_args):raise AssertionError('No client add without a durable ACK')
    async def noop(*_args,**_kwargs):pass
    def busy(*_args,**_kwargs):raise sqlite3.OperationalError('database is locked')
    monkeypatch.setattr(handle,'TrackerSetup',Setup)
    monkeypatch.setattr(handle,'provision_tracker_torrents',noop)
    monkeypatch.setattr(handle,'check_tracker_image_hosts',noop)
    monkeypatch.setattr(SubmissionJournal,phase,busy)
    asyncio.run(handle.process_trackers(meta,{'DEFAULT':{'smart_image_host_selection':False,'multiScreens':0}},
                Client(),['AITHER'],{'AITHER':Tracker},[],[],bandwidth_control=False))
    status=meta.tracker_status['AITHER']
    assert status['needs_review'] is True
    assert len(posts)==(0 if phase=='begin' else 1)
    assert ('No NEW tracker request' if phase=='begin' else 'Do NOT repost') in status['status_message']

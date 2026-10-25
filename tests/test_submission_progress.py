"""Crash/ack tests with SQLite, generated torrent metadata, and no network."""
# ruff: noqa: S101
import asyncio
import hashlib

import bencodepy
import pytest

from src.meta import Meta
from src.runtime.submission_progress import SubmissionJournal, SubmissionNeedsReviewError


def prepared(tmp_path):
    source = tmp_path / 'movie.mkv'
    source.write_bytes(b'dummy')
    return Meta(base_dir=str(tmp_path), path=str(source), uuid='movie.mkv', filelist=[str(source)], category='MOVIE', name='Movie', trackers=['AITHER'], tracker_status={'AITHER': {'upload': True}})


def torrent_file(meta):
    from pathlib import Path
    path = Path(meta.base_dir) / 'tmp' / meta.uuid / '[AITHER].torrent'
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = bencodepy.encode({b'info': {b'name': b'movie.mkv', b'length': 5, b'piece length': 16384, b'pieces': hashlib.sha1(b'dummy', usedforsecurity=False).digest(), b'private': 1}})
    path.write_bytes(raw)
    return path, raw


def test_uncertain_post_requires_fresh_one_shot_confirmation(tmp_path):
    meta = prepared(tmp_path)
    store = SubmissionJournal.for_meta(meta)
    assert store.begin('AITHER')
    with pytest.raises(SubmissionNeedsReviewError, match='active'):
        store.begin('AITHER')
    store.uncertain('AITHER')
    token = store.lookup('AITHER')['nonce']
    with pytest.raises(SubmissionNeedsReviewError, match='may have reached'):
        store.begin('AITHER')
    assert store.begin('AITHER', confirmation=token)
    store.uncertain('AITHER')
    assert store.lookup('AITHER')['nonce'] != token
    with pytest.raises(SubmissionNeedsReviewError):
        store.begin('AITHER', confirmation=token)


def test_ack_restores_exact_torrent_without_reposting(tmp_path):
    meta = prepared(tmp_path)
    path, raw = torrent_file(meta)
    store = SubmissionJournal.for_meta(meta)
    store.begin('AITHER')
    meta.tracker_status['AITHER']['torrent_id'] = 42
    store.acknowledge('AITHER', meta)
    assert store.begin('AITHER') is False
    path.write_bytes(b'wrong recreated artifact')
    assert store.restore_torrent('AITHER', meta)
    assert path.read_bytes() == raw
    assert (store.path.stat().st_mode & 0o777) == 0o600


def test_tracker_post_is_not_repeated_after_client_add_failure(tmp_path, monkeypatch):
    import src.trackerhandle as handle
    posts, additions = [], []
    class Setup:
        def __init__(self, **kwargs):
            pass
        def trackers_enabled(self, _meta):
            return ['AITHER']
    class Tracker:
        tracker = 'AITHER'
        torrent_url = 'https://aither.cc/torrents/'
        def __init__(self, **kwargs):
            pass
        async def upload(self, meta):
            posts.append('POST')
            torrent_file(meta)
            meta.tracker_status['AITHER']['torrent_id'] = 42
            return True
    class Client:
        async def add_to_client(self, _meta, tracker):
            additions.append(tracker)
            if len(additions) == 1:
                raise RuntimeError('simulated interruption after site ACK')
    async def noop(*args, **kwargs):
        pass
    monkeypatch.setattr(handle, 'TrackerSetup', Setup)
    monkeypatch.setattr(handle, 'provision_tracker_torrents', noop)
    monkeypatch.setattr(handle, 'check_tracker_image_hosts', noop)
    cfg = {'DEFAULT': {'smart_image_host_selection': False, 'multiScreens': 0}}
    client = Client()
    meta = prepared(tmp_path)
    asyncio.run(handle.process_trackers(meta, cfg, client, ['AITHER'], {'AITHER': Tracker}, [], [], bandwidth_control=False))
    # New process metadata with the SAME unchanged source; no legacy status reused.
    fresh = Meta(base_dir=meta.base_dir, path=meta.path, uuid=meta.uuid, filelist=meta.filelist, category='MOVIE', name='Movie', trackers=['AITHER'], tracker_status={'AITHER': {'upload': True}})
    asyncio.run(handle.process_trackers(fresh, cfg, client, ['AITHER'], {'AITHER': Tracker}, [], [], bandwidth_control=False))
    assert posts == ['POST']
    assert additions == ['AITHER', 'AITHER']
    assert fresh.tracker_status['AITHER']['upload_success'] is True

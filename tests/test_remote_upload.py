"""Synthetic jobs only: no network, tracker POSTs or real payload mutation."""
# ruff: noqa: S101
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.remote_upload import Jobs, load_engine


@pytest.fixture
def setup():
    c = SimpleNamespace(ledger={"stages": {}}, save=Mock(), return_torrent=Mock())
    engine = load_engine()
    jobs = Jobs(c, SimpleNamespace(safe_relative=engine.safe_relative, RefuseError=engine.RefuseError), clock=lambda: 100)
    return jobs, c


def test_stage_requires_verified_record(setup):
    jobs, c = setup
    def stage(_source):
        c.ledger['stages']['s'] = {'id': 's', 'state': 'ready'}
    c.stage = stage
    id_ = jobs.stage('/dummy.mkv', 10)
    assert jobs.jobs[id_]['state'] == 'staged'
    for delay in (-1, float('nan'), float('inf')):
        with pytest.raises(ValueError):
            jobs.stage('/dummy.mkv', delay)


def test_due_return_calls_verified_engine_once(setup):
    jobs, c = setup
    jobs.jobs['j'] = {'state': 'seeding', 'torrents': {'abc': {'state': 'seeding', 'due': 100}}}
    jobs.tick()
    jobs.tick()
    c.return_torrent.assert_called_once_with('abc', confirmed=True)
    assert jobs.jobs['j']['state'] == 'returned'


def test_interval_not_elapsed_does_not_return(setup):
    jobs, c = setup
    jobs.jobs['j'] = {'state': 'seeding', 'torrents': {'abc': {'state': 'seeding', 'due': 101}}}
    jobs.tick()
    c.return_torrent.assert_not_called()


def test_return_failure_not_retried_or_cleaned(setup):
    jobs, c = setup
    c.return_torrent.side_effect = RuntimeError('connection lost')
    jobs.jobs['j'] = {'state': 'seeding', 'torrents': {'abc': {'state': 'seeding', 'due': 99}}}
    jobs.tick()
    jobs.tick()
    assert jobs.jobs['j']['state'] == 'needs_review'
    assert c.return_torrent.call_count == 1


def test_ambiguous_upload_never_replayed(setup):
    jobs, _c = setup
    jobs.jobs['j'] = {'state': 'uploading'}
    with pytest.raises(ValueError):
        jobs.run('j', ['PTP'])


def test_remote_upload_only_adopts_this_stage(setup):
    jobs, c = setup
    c.cfg = {'remote': {'host': 'dummy', 'user': 'dummy', 'port': 22}, 'known_hosts': '/dummy/hosts', 'remote_ua_command': ['python', 'upload.py']}
    c.ledger['stages']['s'] = {'id': 's', 'state': 'ready', 'remote_input': '/nvme/file.mkv'}
    jobs.jobs['j'] = {'state': 'staged', 'stage': 's', 'delay': 60, 'torrents': {}}
    rows = [{'hash': 'new', 'save_path': '/nvme'}, {'hash': 'unrelated', 'save_path': '/nvme'}]
    jobs.engine.qb_pages = Mock(side_effect=[[], rows])
    c.peer = SimpleNamespace(qb=Mock(return_value=[{'name': 'file.mkv'}]), rpc=Mock(side_effect=[[{'origin': ['s', 'file.mkv']}], [{'origin': ['other', 'file.mkv']}]]))
    runner = Mock()
    jobs.run('j', ['PTP'], runner)
    assert jobs.jobs['j']['torrents'] == {'new': {'state': 'seeding', 'due': 160}}
    assert '/nvme/file.mkv' in runner.call_args.args[0][-1]


def test_upload_failure_is_manual_review(setup):
    jobs, c = setup
    c.cfg = {'remote': {'host': 'dummy', 'user': 'dummy', 'port': 22}, 'known_hosts': '/dummy/hosts', 'remote_ua_command': ['python', 'upload.py']}
    c.ledger['stages']['s'] = {'id': 's', 'state': 'ready', 'remote_input': '/nvme/file.mkv'}
    c.peer = SimpleNamespace(qb=Mock())
    jobs.engine.qb_pages = Mock(return_value=[])
    jobs.jobs['j'] = {'state': 'staged', 'stage': 's', 'delay': 60, 'torrents': {}}
    with pytest.raises(RuntimeError):
        jobs.run('j', ['PTP'], Mock(side_effect=RuntimeError('disconnect')))
    assert jobs.jobs['j']['state'] == 'needs_review'

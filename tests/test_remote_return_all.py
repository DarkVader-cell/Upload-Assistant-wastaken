"""All due registrations use the same guarded return path; no live qB calls."""
# ruff: noqa: S101
from types import SimpleNamespace
from unittest.mock import Mock, call

from src.remote_upload import Jobs


def test_all_due_tracker_torrents_use_confirmed_guarded_return():
    controller=SimpleNamespace(ledger={'stages':{}},save=Mock(),return_torrent=Mock())
    jobs=Jobs(controller,SimpleNamespace(),clock=lambda:100)
    hashes=['a'*40,'b'*40,'c'*40,'d'*40]
    jobs.jobs['job']={'state':'seeding','torrents':{hash_:{'state':'seeding','due':99} for hash_ in hashes}}
    jobs.tick()
    assert controller.return_torrent.call_args_list==[call(hash_,confirmed=True) for hash_ in hashes]
    assert jobs.jobs['job']['state']=='returned'
    assert all(item['state']=='returned' for item in jobs.jobs['job']['torrents'].values())
    jobs.tick()
    assert controller.return_torrent.call_count==len(hashes)

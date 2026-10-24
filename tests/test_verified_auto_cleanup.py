"""Scheduler cleanup policy with fake peers; no deletion or tracker calls."""
# ruff: noqa: S101
from types import SimpleNamespace
from unittest.mock import Mock

from src.remote_upload import Jobs


class RefusalError(RuntimeError):
    pass


def setup(enabled):
    controller=SimpleNamespace(cfg={'auto_cleanup_verified':enabled},ledger={'stages':{'a':{'state':'ready'},'failed':{'state':'ready'}},'returns':{'h':{'state':'returned'}}},save=Mock())
    controller.cleanup=Mock()
    jobs=Jobs(controller,SimpleNamespace(RefuseError=RefusalError),clock=lambda:100)
    jobs.jobs['done']={'stage':'a','state':'returned','torrents':{'h':{'state':'returned'}}}
    jobs.jobs['failed']={'stage':'failed','state':'needs_review','torrents':{}}
    return jobs,controller


def test_automatic_cleanup_is_opt_in():
    jobs,c=setup(False)
    jobs.tick()
    c.cleanup.assert_not_called()
    assert jobs.jobs['done']['state']=='returned'


def test_only_verified_returned_job_is_cleaned_once():
    jobs,c=setup(True)
    def clean(**_kwargs):
        c.ledger['stages']['a']['state']='cleaned'
        c.ledger['returns']['h']['state']='cleaned'
        return {'removed_files':2}
    c.cleanup.side_effect=clean
    jobs.tick()
    c.cleanup.assert_called_once_with(confirmed=True,stage_ids=['a'])
    assert jobs.jobs['done']['state']=='cleaned'
    assert jobs.jobs['done']['torrents']['h']['state']=='cleaned'
    assert jobs.jobs['failed']['state']=='needs_review'
    assert c.ledger['stages']['failed']['state']=='ready'
    jobs.tick()
    assert c.cleanup.call_count==1


def test_blocked_cleanup_retains_returned_state_and_backs_off():
    jobs,c=setup(True)
    c.cleanup.side_effect=RefusalError('Unknown hardlinks; keep data')
    jobs.tick()
    assert jobs.jobs['done']['state']=='returned'
    assert jobs.jobs['done']['cleanup_status']=='blocked'
    assert jobs.jobs['done']['cleanup_retry_at']==400
    assert 'Unknown hardlinks' in jobs.jobs['done']['cleanup_error']
    jobs.tick()
    assert c.cleanup.call_count==1
    assert c.ledger['returns']['h']['state']=='returned'

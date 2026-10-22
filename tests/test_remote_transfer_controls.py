"""Dummy process identities/signals only; never signal real jobs or trackers."""
# ruff: noqa: S101
import json
import signal
from unittest.mock import Mock

import pytest

from src import remote_transfer_control as control


def record():
    return {'id':'a'*32,'state':'copying','writer_pid':1234,'writer_start':'777','writer_pgid':4321,'bytes_total':1000,'bytes_sent':400,'bytes_per_second':100}


def test_pause_resume_cancel_and_eta(tmp_path, monkeypatch):
    monkeypatch.setattr(control,'process_start',lambda _pid:'777')
    monkeypatch.setattr(control.os,'getpgid',lambda _pid:4321)
    monkeypatch.setattr(control.os,'getpgrp',lambda:99)
    kill=Mock()
    monkeypatch.setattr(control.os,'killpg',kill)
    r=record()
    assert control.transfer_status(tmp_path,r)['eta_seconds']==6
    control.control_transfer(tmp_path,r,'pause')
    kill.assert_called_with(4321,signal.SIGSTOP)
    assert control.transfer_status(tmp_path,r)['state']=='paused'
    assert control.transfer_status(tmp_path,r)['eta_seconds'] is None
    control.control_transfer(tmp_path,r,'resume')
    kill.assert_called_with(4321,signal.SIGCONT)
    control.control_transfer(tmp_path,r,'cancel')
    assert kill.call_args_list[-2].args==(4321,signal.SIGCONT)
    assert kill.call_args_list[-1].args==(4321,signal.SIGINT)
    assert control.transfer_status(tmp_path,r)['can_control'] is False
    assert json.loads(control.control_path(tmp_path,r['id']).read_text())['action']=='cancel'


def test_stale_pid_or_completed_stage_is_never_signalled(tmp_path,monkeypatch):
    monkeypatch.setattr(control,'process_start',lambda _pid:'different-process')
    kill=Mock()
    monkeypatch.setattr(control.os,'killpg',kill)
    with pytest.raises(ValueError):
        control.control_transfer(tmp_path,record(),'cancel')
    kill.assert_not_called()
    assert control.transfer_status(tmp_path,record())['state']=='interrupted'
    r=record()
    r['state']='ready'
    with pytest.raises(ValueError):
        control.control_transfer(tmp_path,r,'pause')
    assert control.transfer_status(tmp_path,r)['can_discard'] is False


def test_legacy_stage_has_no_destructive_controls(tmp_path):
    r={'id':'b'*32,'state':'copying','bytes_total':100,'bytes_sent':20,'bytes_per_second':10}
    result=control.transfer_status(tmp_path,r)
    assert result['eta_seconds']==8
    assert result['can_control'] is False and result['can_discard'] is False

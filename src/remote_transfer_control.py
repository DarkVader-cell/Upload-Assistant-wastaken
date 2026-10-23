"""Local transfer controls with PID-reuse protection; never guess file deletion."""
import json
import math
import os
import re
import signal
from pathlib import Path

from src.config_io import atomic_write_text


def process_start(pid):
    try:
        return Path(f'/proc/{int(pid)}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, ValueError, IndexError, TypeError):
        return None


def control_path(state, id_):
    if not isinstance(id_, str) or not re.fullmatch('[a-f0-9]{32}', id_):
        raise ValueError('Invalid stage identifier')
    return Path(state) / 'controls' / (id_ + '.json')


def transfer_status(state, record):
    control = control_path(state, record['id'])
    value = json.loads(control.read_text()) if control.exists() else {}
    live = bool(record.get('writer_start') and process_start(record.get('writer_pid')) == record['writer_start'])
    phase = record.get('state')
    if live and phase == 'copying' and value.get('action') in {'pause', 'cancel'}:
        phase = 'paused' if value['action'] == 'pause' else 'cancelling'
    if record.get('writer_start') and not live and phase == 'copying':
        phase = 'interrupted'
    rate = max(0, float(record.get('bytes_per_second', 0)))
    remaining = max(0, record.get('bytes_total', 0) - record.get('bytes_sent', 0))
    return {'state': phase, 'writer_live': live, 'can_control': live and record.get('state') == 'copying' and value.get('action') != 'cancel',
            'eta_seconds': math.ceil(remaining / rate) if phase == 'copying' and rate > 0 else None,
            'can_discard': bool(record.get('writer_start')) and not live and record.get('state') in {'copying', 'interrupted'}}


def control_transfer(state, record, action):
    if action not in {'pause', 'resume', 'cancel'}:
        raise ValueError('Unsupported transfer control')
    path = control_path(state, record['id'])
    if record.get('state') != 'copying' or not record.get('writer_start') or process_start(record.get('writer_pid')) != record['writer_start']:
        raise ValueError('No matching live transfer; completed/uploading/legacy jobs cannot be signalled')
    group = os.getpgid(record['writer_pid'])
    if group != record.get('writer_pgid') or group == os.getpgrp():
        raise ValueError('Transfer process group identity mismatch')
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Record intent separately: the controller owns/locks the main ledger.
    atomic_write_text(path, json.dumps({'action': action}), default_mode=0o600)
    if action == 'cancel':
        os.killpg(group, signal.SIGCONT)
    os.killpg(group, {'pause': signal.SIGSTOP, 'resume': signal.SIGCONT, 'cancel': signal.SIGINT}[action])
    return {'state': {'pause': 'paused', 'resume': 'copying', 'cancel': 'cancelling'}[action]}

#!/usr/bin/env python3
"""Install a per-user return timer for one operator-configured remote backend."""
# ruff: noqa: S603 -- unit name validated by restrictive regex, no shell
import argparse
import json
import re
import subprocess
from pathlib import Path


def quote(value):
    value = str(value)
    if any(c in value for c in '\n\r\x00'):
        raise ValueError('Invalid systemd argument')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--python', required=True, type=Path)
    parser.add_argument('--name', default='default')
    parser.add_argument('--enable', action='store_true', help='Enable and start the timer; does not run a transfer immediately')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', args.name):
        raise ValueError('Invalid backend name')
    config = args.config.expanduser().resolve(strict=True)
    python = args.python.expanduser().absolute()
    if not python.is_file():
        raise ValueError('Python interpreter does not exist')
    cfg = json.loads(config.read_text())
    if not cfg.get('ssh_key'):
        raise ValueError('Timer requires an already-authorized SSH key; none will be installed automatically')
    root = Path(__file__).resolve().parents[1]
    units = Path.home() / '.config/systemd/user'
    units.mkdir(parents=True, exist_ok=True)
    name = 'ua-remote-return-' + args.name
    (units / (name + '.service')).write_text('[Unit]\nDescription=UA verified remote registration return\nAfter=network-online.target\n\n[Service]\nType=oneshot\nUMask=0077\nWorkingDirectory=' + quote(root) + '\nExecStart=' + quote(python) + ' -m src.remote_upload --config ' + quote(config) + ' tick\nStandardInput=null\nTimeoutStartSec=infinity\n')
    (units / (name + '.timer')).write_text('[Unit]\nDescription=Check due UA remote returns every minute\n\n[Timer]\nOnCalendar=*-*-* *:*:00\nPersistent=true\nRandomizedDelaySec=10\nUnit=' + name + '.service\n\n[Install]\nWantedBy=timers.target\n')
    subprocess.run(['/usr/bin/systemctl', '--user', 'daemon-reload'], check=True)
    if args.enable:
        subprocess.run(['/usr/bin/systemctl', '--user', 'enable', '--now', name + '.timer'], check=True)
    print('Installed', name + '.timer')
    print('For operation after logout, the host administrator must enable user lingering if not already enabled.')


if __name__ == '__main__':
    main()

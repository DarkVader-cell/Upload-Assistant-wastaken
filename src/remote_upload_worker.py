"""Detached WebUI worker. Operation records contain no subprocess output/secrets."""
# ruff: noqa: S603 -- fixed interpreter/module with parent-validated argv, no shell
import json
import subprocess
import sys
from pathlib import Path

from src.config_io import atomic_write_text


def main():
    record, config, action, *arguments = sys.argv[1:]
    path = Path(record)
    if path.is_symlink():
        raise ValueError('Operation record must not be a symlink')
    path.chmod(0o600)
    data = json.loads(path.read_text())
    data['state'] = 'running'
    atomic_write_text(path, json.dumps(data), default_mode=0o600)
    try:
        result = subprocess.run([sys.executable, '-m', 'src.remote_upload', '--config', config, action, *arguments], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        data['state'] = 'completed' if result.returncode == 0 else 'needs_review'
    except Exception:
        data['state'] = 'needs_review'
    atomic_write_text(path, json.dumps(data), default_mode=0o600)


if __name__ == '__main__':
    main()

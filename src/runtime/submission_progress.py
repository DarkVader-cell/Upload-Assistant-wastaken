"""Durable POST intent/acknowledgement; a restart is not permission to repost."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

from torf import TorfError, Torrent


class SubmissionNeedsReviewError(RuntimeError):
    pass


def _owner():
    try:
        text = Path(f'/proc/{os.getpid()}/stat').read_text()
        return f'{os.getpid()}:{text.rsplit(")", 1)[1].split()[19]}'
    except OSError:
        return str(os.getpid())


def _alive(owner):
    try:
        pid, _, start = owner.partition(':')
        os.kill(int(pid), 0)
        if start:
            text = Path(f'/proc/{pid}/stat').read_text()
            return text.rsplit(')', 1)[1].split()[19] == start
        return True
    except (OSError, ValueError, IndexError):
        return False


class SubmissionJournal:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        self.path = directory / 'submissions.sqlite'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS submissions (tracker TEXT PRIMARY KEY, state TEXT, owner TEXT, torrent TEXT, digest TEXT, status TEXT, nonce TEXT)')
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @classmethod
    def for_meta(cls, meta):
        if meta.debug or meta.hdb_offer or meta.hdb_manual or not meta.base_dir or not meta.uuid or not meta.path:
            return None
        try:
            root = Path(meta.path).resolve()
            files = [str(p) for p in (meta.filelist or [])]
            if not files:
                files = [str(root)] if root.is_file() else [str(p) for p in root.rglob('*') if p.is_file()]
            files.extend(str(p) for p in (meta.subtitle_files or []))
            if not files:
                raise SubmissionNeedsReviewError('No regular payload files could be identified; submission was not started')
            digest = hashlib.sha256(json.dumps(['submission-progress-v1', str(root)]).encode())
            # Stream the metadata fingerprint: large game/disc trees must not
            # allocate another giant JSON copy of the complete file list.
            for value in sorted(set(files)):
                path = Path(value).resolve(strict=True)
                stat = path.stat()
                if not path.is_file():
                    raise SubmissionNeedsReviewError(f'Payload entry is not a regular file: {path}; submission was not started')
                digest.update(json.dumps((str(path), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)).encode())
            return cls(Path(meta.base_dir) / 'data/cache/submissions' / digest.hexdigest())
        except (OSError, sqlite3.Error) as error:
            # No durable intent storage means no safe submission guard.
            raise SubmissionNeedsReviewError(f'Cannot bind durable submission intent ({type(error).__name__}: {error}); verify payload availability and writable data/cache/submissions before uploading') from None

    def lookup(self, tracker):
        with self.connect() as db:
            row = db.execute('SELECT * FROM submissions WHERE tracker=?', (tracker,)).fetchone()
            return dict(row) if row else None

    def begin(self, tracker, *, confirmation=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM submissions WHERE tracker=?', (tracker,)).fetchone()
            if row:
                if row['state'] == 'posting' and _alive(row['owner']):
                    raise SubmissionNeedsReviewError(f'{tracker}: another submission is still active; do not start a second POST')
                if confirmation != row['nonce']:
                    if row['state'] == 'acknowledged' and confirmation is None:
                        return False
                    raise SubmissionNeedsReviewError(f'{tracker}: a previous POST may have reached the site. Verify it on-site; only then use --confirm-not-uploaded {tracker}:{row["nonce"]}. This permission is valid for only this interrupted attempt.')
            db.execute('INSERT OR REPLACE INTO submissions VALUES (?, ?, ?, NULL, NULL, NULL, ?)', (tracker, 'posting', _owner(), str(uuid.uuid4())))
        return True

    def uncertain(self, tracker):
        with self.connect() as db:
            db.execute('UPDATE submissions SET state=? WHERE tracker=?', ('needs_review', tracker))

    def acknowledge(self, tracker, meta):
        status = meta.tracker_status.get(tracker, {})
        safe_status = {key: status[key] for key in ('torrent_id',) if key in status}
        # Commit the ACK even if retaining the exact torrent subsequently fails.
        with self.connect() as db:
            db.execute('UPDATE submissions SET state=?, status=? WHERE tracker=?', ('acknowledged', json.dumps(safe_status), tracker))
        source = Path(meta.base_dir) / 'tmp' / meta.uuid / f'[{tracker}].torrent'
        if not source.is_file() or source.is_symlink():
            return
        content = source.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        with self.connect() as db:
            db.execute('UPDATE submissions SET digest=? WHERE tracker=?', (digest, tracker))
        target = self.directory / (digest + '.torrent')
        try:
            fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(content)
        except FileExistsError:
            pass
        with self.connect() as db:
            db.execute('UPDATE submissions SET torrent=?, digest=? WHERE tracker=?', (target.name, digest, tracker))

    def restore_torrent(self, tracker, meta):
        row = self.lookup(tracker)
        if not row or row['state'] != 'acknowledged' or not row['digest']:
            return False
        source = self.directory / row['torrent'] if row['torrent'] else Path(meta.base_dir) / 'tmp' / meta.uuid / f'[{tracker}].torrent'
        if row['torrent'] and source.parent != self.directory:
            return False
        target = Path(meta.base_dir) / 'tmp' / meta.uuid / f'[{tracker}].torrent'
        for candidate in dict.fromkeys((source, target)):
            if candidate.is_symlink():
                continue
            try:
                content = candidate.read_bytes()
                if hashlib.sha256(content).hexdigest() != row['digest']:
                    continue
                Torrent.read(candidate)  # Filename/digest alone is not valid torrent metadata.
                target.parent.mkdir(parents=True, exist_ok=True)
                fd, temporary_name = tempfile.mkstemp(prefix=target.name + '.resume-', dir=target.parent)
                temporary = Path(temporary_name)
                try:
                    with os.fdopen(fd, 'wb') as stream:
                        stream.write(content)
                    temporary.replace(target)
                finally:
                    temporary.unlink(missing_ok=True)
                meta.tracker_status.setdefault(tracker, {}).update(json.loads(row['status'] or '{}'))
                return True
            except (OSError, ValueError, TorfError):
                continue
        return False

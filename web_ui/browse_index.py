"""Persistent, low-I/O filename index for the Web UI file browser."""

# SQL statements below use only locally generated placeholder fragments.
# ruff: noqa: S608

from __future__ import annotations

import contextlib
import ctypes
import ctypes.util
import os
import re
import select
import sqlite3
import struct
import threading
import time
from pathlib import Path
from typing import Any

_SEARCH_SEP_RE = re.compile(r"[\s.\-_]+")

_IN_ACCESS = 0x00000001
_IN_MODIFY = 0x00000002
_IN_ATTRIB = 0x00000004
_IN_CLOSE_WRITE = 0x00000008
_IN_MOVED_FROM = 0x00000040
_IN_MOVED_TO = 0x00000080
_IN_CREATE = 0x00000100
_IN_DELETE = 0x00000200
_IN_DELETE_SELF = 0x00000400
_IN_MOVE_SELF = 0x00000800
_IN_IGNORED = 0x00008000
_IN_Q_OVERFLOW = 0x00004000
_WATCH_MASK = _IN_CREATE | _IN_DELETE | _IN_MOVED_FROM | _IN_MOVED_TO | _IN_DELETE_SELF | _IN_MOVE_SELF
_INOTIFY_EVENT = struct.Struct("iIII")


class BrowseIndex:
    """Index file and directory names so interactive searches avoid disk walks.

    The index is deliberately refreshed infrequently. A refresh walks the roots
    once, then replaces their rows atomically. Searches continue using the old
    snapshot while a refresh is running.
    """

    def __init__(self, database_path: str | Path, refresh_seconds: int = 900) -> None:
        self.database_path = Path(database_path)
        self.refresh_seconds = max(30, int(refresh_seconds))
        self._refresh_lock = threading.Lock()
        self._refresh_thread: threading.Thread | None = None
        self._initialized = False
        self._initialize_lock = threading.Lock()
        self._watch_thread: threading.Thread | None = None
        self._watch_roots: tuple[str, ...] = ()
        self._watch_stop = threading.Event()

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize(self) -> None:
        if self._initialized:
            return
        with self._initialize_lock:
            if self._initialized:
                return
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS browse_entries (
                        root TEXT NOT NULL,
                        path TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        name_lower TEXT NOT NULL,
                        entry_type TEXT NOT NULL
                    )
                    """
                )
                connection.execute("CREATE INDEX IF NOT EXISTS idx_browse_name_lower ON browse_entries(name_lower)")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS browse_roots (
                        root TEXT PRIMARY KEY,
                        scanned_at REAL NOT NULL
                    )
                    """
                )
            self._initialized = True

    @staticmethod
    def _normalized_roots(roots: list[str]) -> list[str]:
        return sorted({str(Path(root).resolve()) for root in roots if Path(root).is_dir()})

    def _needs_refresh(self, roots: list[str]) -> bool:
        if not roots:
            return False
        now = time.time()
        with self._connect() as connection:
            rows = connection.execute("SELECT root, scanned_at FROM browse_roots").fetchall()
        scanned = {str(row["root"]): float(row["scanned_at"]) for row in rows}
        return any(root not in scanned or now - scanned[root] >= self.refresh_seconds for root in roots)

    def _refresh(self, roots: list[str]) -> None:
        roots = self._normalized_roots(roots)
        if not roots or not self._refresh_lock.acquire(blocking=False):
            return
        try:
            self._initialize()
            now = time.time()
            with self._connect() as connection:
                for root in roots:
                    # Build the replacement set in one transaction so readers
                    # see either the old index or the complete new snapshot.
                    connection.execute("DELETE FROM browse_entries WHERE root = ?", (root,))
                    batch: list[tuple[str, str, str, str, str]] = []
                    for dirpath, dirnames, filenames in os.walk(root):
                        dirnames[:] = [name for name in dirnames if not name.startswith(".")]
                        for dirname in dirnames:
                            path = str(Path(dirpath) / dirname)
                            batch.append((root, path, dirname, dirname.casefold(), "folder"))
                        for filename in filenames:
                            if filename.startswith("."):
                                continue
                            path = str(Path(dirpath) / filename)
                            batch.append((root, path, filename, filename.casefold(), "file"))
                        if len(batch) >= 2000:
                            connection.executemany(
                                "INSERT OR REPLACE INTO browse_entries(root, path, name, name_lower, entry_type) VALUES (?, ?, ?, ?, ?)",
                                batch,
                            )
                            batch.clear()
                    if batch:
                        connection.executemany(
                            "INSERT OR REPLACE INTO browse_entries(root, path, name, name_lower, entry_type) VALUES (?, ?, ?, ?, ?)",
                            batch,
                        )
                    connection.execute("INSERT OR REPLACE INTO browse_roots(root, scanned_at) VALUES (?, ?)", (root, now))
        finally:
            self._refresh_lock.release()

    def _start_refresh(self, roots: list[str]) -> None:
        if self._refresh_thread is not None and self._refresh_thread.is_alive():
            return
        self._refresh_thread = threading.Thread(target=self._refresh, args=(roots,), name="ua-browse-index", daemon=True)
        self._refresh_thread.start()

    def _upsert_entry(self, connection: sqlite3.Connection, root: str, path: Path, entry_type: str) -> None:
        name = path.name
        if not name or name.startswith("."):
            return
        connection.execute(
            "INSERT OR REPLACE INTO browse_entries(root, path, name, name_lower, entry_type) VALUES (?, ?, ?, ?, ?)",
            (root, str(path), name, name.casefold(), entry_type),
        )

    def _delete_path(self, connection: sqlite3.Connection, path: Path) -> None:
        prefix = str(path).rstrip(os.sep) + os.sep + "%"
        connection.execute("DELETE FROM browse_entries WHERE path = ? OR path LIKE ?", (str(path), prefix))

    def _sync_directory(self, root: str, directory: Path) -> None:
        """Synchronize one changed directory, not the whole browse root."""
        if not directory.is_dir():
            return
        with self._connect() as connection:
            batch: list[tuple[str, str, str, str, str]] = []
            try:
                entries = list(os.scandir(directory))
                direct_paths = {str(Path(entry.path)) for entry in entries}
                existing = connection.execute("SELECT path FROM browse_entries WHERE root = ?", (root,)).fetchall()
                for row in existing:
                    existing_path = Path(str(row["path"]))
                    if existing_path.parent == directory and str(existing_path) not in direct_paths:
                        connection.execute("DELETE FROM browse_entries WHERE path = ?", (str(existing_path),))
                for entry in entries:
                    if entry.name.startswith("."):
                        continue
                    entry_type = "folder" if entry.is_dir(follow_symlinks=False) else "file"
                    batch.append((root, entry.path, entry.name, entry.name.casefold(), entry_type))
            except (PermissionError, OSError):
                return
            connection.executemany(
                "INSERT OR REPLACE INTO browse_entries(root, path, name, name_lower, entry_type) VALUES (?, ?, ?, ?, ?)",
                batch,
            )
            connection.execute("INSERT OR REPLACE INTO browse_roots(root, scanned_at) VALUES (?, ?)", (root, time.time()))

    def _sync_subtree(self, root: str, directory: Path) -> None:
        """Index a newly-created directory and its descendants."""
        if not directory.is_dir():
            return
        with self._connect() as connection:
            batch: list[tuple[str, str, str, str, str]] = []

            def flush_batch() -> None:
                if not batch:
                    return
                connection.executemany(
                    "INSERT OR REPLACE INTO browse_entries(root, path, name, name_lower, entry_type) VALUES (?, ?, ?, ?, ?)",
                    batch,
                )
                batch.clear()

            try:
                for dirpath, dirnames, filenames in os.walk(directory):
                    dirnames[:] = [name for name in dirnames if not name.startswith(".")]
                    for dirname in dirnames:
                        path = Path(dirpath) / dirname
                        batch.append((root, str(path), dirname, dirname.casefold(), "folder"))
                    for filename in filenames:
                        if filename.startswith("."):
                            continue
                        path = Path(dirpath) / filename
                        batch.append((root, str(path), filename, filename.casefold(), "file"))
                    # A newly moved media directory can contain tens of
                    # thousands of entries. Keep the SQLite transaction, but
                    # bound Python memory while populating it.
                    if len(batch) >= 2000:
                        flush_batch()
                flush_batch()
                connection.execute("INSERT OR REPLACE INTO browse_roots(root, scanned_at) VALUES (?, ?)", (root, time.time()))
            except (PermissionError, OSError):
                return

    def _watcher_available(self) -> bool:
        return os.name == "posix" and ctypes.util.find_library("c") is not None

    def _indexed_directories(self, roots: tuple[str, ...]) -> list[tuple[str, Path]]:
        """Return watcher targets from the existing index without another disk walk."""
        placeholders = ",".join("?" for _ in roots)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT root, path FROM browse_entries "
                f"WHERE root IN ({placeholders}) AND entry_type = 'folder'",
                roots,
            ).fetchall()
        directories = [(root, Path(root)) for root in roots]
        directories.extend((str(row["root"]), Path(str(row["path"]))) for row in rows)
        return directories

    def _watch_filesystem(self, roots: tuple[str, ...]) -> None:
        """Consume Linux inotify events and update only affected paths."""
        libc_name = ctypes.util.find_library("c")
        if not libc_name:
            return
        libc = ctypes.CDLL(libc_name, use_errno=True)
        init = getattr(libc, "inotify_init1", None)
        add_watch = getattr(libc, "inotify_add_watch", None)
        rm_watch = getattr(libc, "inotify_rm_watch", None)
        if init is None or add_watch is None or rm_watch is None:
            return
        fd = int(init(os.O_NONBLOCK))
        if fd < 0:
            return
        watches: dict[int, tuple[str, Path]] = {}

        def add_directory(root: str, directory: Path) -> None:
            if not directory.is_dir() or directory.name.startswith("."):
                return
            watch_descriptor = int(add_watch(fd, os.fsencode(str(directory)), _WATCH_MASK))
            if watch_descriptor >= 0:
                watches[watch_descriptor] = (root, directory)

        try:
            # The refresh already discovered every directory. Reuse that
            # snapshot so enabling live updates does not immediately perform a
            # second full HDD traversal.
            for root, directory in self._indexed_directories(roots):
                add_directory(root, directory)
            poller = select.poll()
            poller.register(fd, select.POLLIN)
            while not self._watch_stop.is_set():
                if not poller.poll(1000):
                    continue
                try:
                    data = os.read(fd, 1024 * 1024)
                except BlockingIOError:
                    continue
                offset = 0
                while offset + _INOTIFY_EVENT.size <= len(data):
                    watch_descriptor, mask, _cookie, name_length = _INOTIFY_EVENT.unpack_from(data, offset)
                    offset += _INOTIFY_EVENT.size
                    raw_name = data[offset : offset + name_length]
                    offset += name_length
                    watched = watches.get(watch_descriptor)
                    if mask & _IN_Q_OVERFLOW:
                        self._start_refresh(list(roots))
                        continue
                    if watched is None:
                        continue
                    root, directory = watched
                    name = os.fsdecode(raw_name).rstrip("\x00")
                    changed = directory / name if name else directory
                    if mask & _IN_IGNORED:
                        watches.pop(watch_descriptor, None)
                    elif mask & (_IN_DELETE | _IN_MOVED_FROM | _IN_DELETE_SELF | _IN_MOVE_SELF):
                        with self._connect() as connection:
                            self._delete_path(connection, changed)
                            connection.execute("INSERT OR REPLACE INTO browse_roots(root, scanned_at) VALUES (?, ?)", (root, time.time()))
                    elif mask & (_IN_CREATE | _IN_MOVED_TO):
                        if changed.is_dir():
                            with self._connect() as connection:
                                self._upsert_entry(connection, root, changed, "folder")
                            self._sync_subtree(root, changed)
                            for dirpath, dirnames, _filenames in os.walk(changed):
                                dirnames[:] = [entry for entry in dirnames if not entry.startswith(".")]
                                for dir_name in dirnames:
                                    add_directory(root, Path(dirpath) / dir_name)
                            add_directory(root, changed)
                        elif changed.is_file():
                            self._sync_directory(root, directory)
        finally:
            self._watch_stop.set()
            for watch_descriptor in list(watches):
                with contextlib.suppress(OSError):
                    rm_watch(fd, watch_descriptor)
            os.close(fd)

    def _start_watcher(self, roots: list[str]) -> None:
        normalized = tuple(self._normalized_roots(roots))
        if not normalized or not self._watcher_available():
            return
        if self._watch_thread is not None and self._watch_thread.is_alive() and self._watch_roots == normalized:
            return
        self._watch_stop.set()
        previous = self._watch_thread
        if previous is not None and previous.is_alive() and previous is not threading.current_thread():
            # A root change is rare. Waiting briefly here prevents a hot reload
            # from leaving two inotify readers and SQLite writers alive.
            previous.join(timeout=1.5)
        self._watch_roots = normalized
        self._watch_stop = threading.Event()
        self._watch_thread = threading.Thread(target=self._watch_filesystem, args=(normalized,), name="ua-browse-watcher", daemon=True)
        self._watch_thread.start()

    def close(self) -> None:
        """Stop the optional watcher during server shutdown or hot reload."""
        self._watch_stop.set()
        watcher = self._watch_thread
        if watcher is not None and watcher.is_alive() and watcher is not threading.current_thread():
            watcher.join(timeout=1.5)
        if watcher is None or not watcher.is_alive():
            self._watch_thread = None
        self._watch_roots = ()

    def search(self, roots: list[str], query: str, file_filter: str, max_results: int) -> tuple[list[dict[str, Any]], bool]:
        """Return indexed candidates and whether an index refresh is running."""
        normalized_roots = self._normalized_roots(roots)
        if not normalized_roots:
            return [], False
        self._initialize()

        with self._connect() as connection:
            indexed_count = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM browse_entries WHERE root IN ({','.join('?' for _ in normalized_roots)})",
                    normalized_roots,
                ).fetchone()[0]
            )

        # The first search gets a usable index synchronously. Later refreshes
        # happen in the background and do not block or repeatedly hit the HDD.
        if indexed_count == 0:
            self._refresh(normalized_roots)
        elif self._needs_refresh(normalized_roots):
            self._start_refresh(normalized_roots)
        self._start_watcher(normalized_roots)

        tokens = [token for token in _SEARCH_SEP_RE.split(query.casefold()) if token]
        if not tokens:
            return [], bool(self._refresh_thread and self._refresh_thread.is_alive())

        clauses = " AND ".join("name_lower LIKE ?" for _ in tokens)
        params: list[object] = [*normalized_roots, *(f"%{token}%" for token in tokens)]
        root_placeholders = ",".join("?" for _ in normalized_roots)
        sql = (
            f"SELECT path, name, entry_type FROM browse_entries "
            f"WHERE root IN ({root_placeholders}) AND {clauses} ORDER BY entry_type, name_lower"
        )
        items: list[dict[str, Any]] = []
        with self._connect() as connection:
            # Do not materialize every partial match before applying the
            # ordered-token check. Large libraries commonly share short
            # release-name tokens, while the caller only needs max_results.
            for row in connection.execute(sql, params):
                name_tokens = [token for token in _SEARCH_SEP_RE.split(str(row["name"]).casefold()) if token]
                position = 0
                matches = True
                for token in tokens:
                    try:
                        position = name_tokens.index(token, position) + 1
                    except ValueError:
                        matches = False
                        break
                if not matches:
                    continue
                if file_filter == "desc" and row["entry_type"] == "file" and Path(str(row["name"]).casefold()).suffix not in {".txt", ".nfo", ".md"}:
                    continue
                items.append({"name": row["name"], "path": row["path"], "type": row["entry_type"]})
                if len(items) >= max_results:
                    break

        return items, bool(self._refresh_thread and self._refresh_thread.is_alive())

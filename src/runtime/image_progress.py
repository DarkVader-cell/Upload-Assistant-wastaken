"""Resume completed image-host uploads without replaying a tracker submission."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

_LOCK = threading.RLock()
_KEYS = ("img_url", "raw_url", "web_url")


class ImageUploadJournal:
    def __init__(self, directory: Path):
        self.path = directory / "image_upload_progress.json"

    @staticmethod
    def key(image: str, host: str) -> str | None:
        try:
            path = Path(image).resolve(strict=True)
            stat = path.stat()
            if not path.is_file():
                return None
            identity = [str(path), host.casefold(), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]
            return hashlib.sha256(json.dumps(identity).encode()).hexdigest()
        except OSError:
            return None

    def _load(self) -> dict:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def get(self, key: str | None) -> dict | None:
        if not key:
            return None
        with _LOCK:
            row = self._load().get(key, {})
            if not isinstance(row, dict) or not isinstance(row.get("saved"), (int, float)) or time.time() - row["saved"] > 7 * 86400:
                return None
            result = row.get("result")
            return dict(result) if self._valid(result) else None

    @staticmethod
    def _valid(result: object) -> bool:
        if not isinstance(result, dict) or result.get("status") != "success":
            return False
        for key in _KEYS:
            value = result.get(key)
            if not isinstance(value, str):
                return False
            try:
                parsed = urlsplit(value)
                if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                    return False
            except ValueError:
                return False
        return True

    def put(self, key: str | None, result: dict) -> None:
        if not key or not self._valid(result):
            return
        # Cache failures must never turn a successful POST into another POST.
        try:
            with _LOCK:
                rows = self._load()
                rows[key] = {"saved": time.time(), "result": {"status": "success", **{k: result[k] for k in _KEYS}}}
                self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                fd, temporary = tempfile.mkstemp(prefix=".image-progress-", dir=self.path.parent)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as stream:
                        json.dump(rows, stream)
                    Path(temporary).replace(self.path)
                finally:
                    Path(temporary).unlink(missing_ok=True)
        except OSError:
            return

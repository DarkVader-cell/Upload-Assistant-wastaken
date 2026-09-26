"""Safe persistence helpers for user-owned runtime configuration files."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path


def ensure_private_directory(path: Path, *, mode: int = 0o700) -> Path:
    """Create a runtime directory with private permissions when it is new."""
    path.mkdir(parents=True, exist_ok=True, mode=mode)
    if os.name != "nt":
        try:
            if stat.S_IMODE(path.stat().st_mode) != mode:
                path.chmod(mode)
        except OSError:
            # The caller will receive the useful error when it attempts to write.
            pass
    return path


def atomic_write_text(path: Path, text: str, *, default_mode: int = 0o600) -> None:
    """Atomically write text while retaining existing mode and user ownership.

    The temporary file is created beside the destination, so replacement does
    not cross filesystems. A new file is private by default because config files
    commonly contain API keys, passwords, and cookies.
    """
    ensure_private_directory(path.parent)
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        mode = default_mode

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(text)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        if os.name != "nt":
            temporary_path.chmod(mode)
        temporary_path.replace(path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

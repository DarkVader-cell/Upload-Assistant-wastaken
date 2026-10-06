"""Authenticated, encrypted transport of explicitly selected configuration sections."""
import ast
import base64
import json
import os
import pprint
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAX_BUNDLE_BYTES = 2 * 1024 * 1024
SECTIONS = frozenset({"DEFAULT", "TRACKERS", "TORRENT_CLIENTS", "USENET"})
# Machine-specific values are never transported. Cookie FILES are not included.
LOCAL_KEYS = frozenset({"local_path", "remote_path", "torrent_storage_dir", "watch_folder", "link_dir", "link_dir_name", "cookie_file", "cookies_file"})
DEFAULT_KEYS = frozenset({"tmdb_api", "tvdb_api", "tvdb_token", "google_books_api_key", "twitch_client_id", "twitch_client_secret", "mam_api_key", "ggn_api_key", "btn_api", "prowlarr_url", "prowlarr_api_key", "music_discogs_token", "default_trackers"})


def read_config(path: Path) -> dict[str, Any]:
    """Parse literals only; exporting/importing must never execute a config file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "config" for t in node.targets)) or (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "config"):
            value = ast.literal_eval(node.value)
            if isinstance(value, dict):
                return value
    raise ValueError("Configuration must contain a literal config dictionary")


def portable_settings(config: dict[str, Any], sections: list[str]) -> dict[str, Any]:
    if not sections or any(section not in SECTIONS for section in sections):
        raise ValueError("Select only DEFAULT, TRACKERS, TORRENT_CLIENTS, or USENET")

    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items() if isinstance(key, str) and key not in LOCAL_KEYS and not key.endswith("_path") and not key.endswith("_dir")}
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value

    result = {}
    for section in sections:
        value = config.get(section, {})
        if not isinstance(value, dict):
            raise ValueError("Selected sections must be dictionaries")
        if section == "DEFAULT":
            value = {key: item for key, item in value.items() if key in DEFAULT_KEYS or key.startswith("img_host_") or key.endswith("_api") or key.endswith("_api_key")}
        result[section] = clean(value)
    return result


def _key(password: str, salt: bytes) -> bytes:
    if len(password) < 12:
        raise ValueError("Use a passphrase of at least 12 characters")
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode())


def encrypt_settings(settings: dict[str, Any], password: str) -> bytes:
    salt, nonce = os.urandom(16), os.urandom(12)
    payload = json.dumps(settings).encode()
    if len(payload) > MAX_BUNDLE_BYTES // 2:
        raise ValueError("Configuration is too large")
    encrypted = AESGCM(_key(password, salt)).encrypt(nonce, payload, b"UA-CONFIG-1")
    return b"UA-CONFIG-1\n" + base64.b64encode(salt + nonce + encrypted)


def decrypt_settings(bundle: bytes, password: str) -> dict[str, Any]:
    if len(bundle) > MAX_BUNDLE_BYTES or not bundle.startswith(b"UA-CONFIG-1\n"):
        raise ValueError("Invalid configuration bundle")
    raw = base64.b64decode(bundle.split(b"\n", 1)[1], validate=True)
    payload = AESGCM(_key(password, raw[:16])).decrypt(raw[16:28], raw[28:], b"UA-CONFIG-1")
    settings = json.loads(payload)
    if not isinstance(settings, dict):
        raise ValueError("Invalid configuration payload")
    # Apply the same allowlist on import, even for an authenticated bundle.
    return portable_settings(settings, list(settings))


def import_settings(path: Path, settings: dict[str, Any], overwrite: bool = False) -> Path:
    from src.config_sync import config_write_lock, replace_config_source

    def merge(current: dict[str, Any], incoming: dict[str, Any]) -> None:
        for key, value in incoming.items():
            if isinstance(value, dict) and isinstance(current.get(key), dict):
                merge(current[key], value)
            elif key not in current or current[key] in (None, "", [], {}) or overwrite:
                current[key] = value

    with config_write_lock(path):
        original = path.read_bytes()
        current = read_config(path)
        merge(current, portable_settings(settings, list(settings)))
        backup = path.with_name(f"{path.name}.backup-bundle-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}")
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(original)
        replace_config_source(path, "config = " + pprint.pformat(current, sort_dicts=False, width=120) + "\n", original)
        path.chmod(0o600)
    return backup

"""Reference cleanup helpers for source-compatible config mutations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def torrent_client_reference_updates(config: Mapping[str, Any], removed_client: str) -> list[tuple[list[str], object | None]]:
    """Return path/value updates needed after deleting a torrent client.

    ``None`` means remove the setting. Client implementation fields inside
    ``TORRENT_CLIENTS`` are intentionally ignored; they name qbit/deluge/etc.,
    not a configured client profile.
    """
    removed = removed_client.strip()
    if not removed:
        return []
    clients = config.get("TORRENT_CLIENTS")
    remaining = sorted(str(name) for name in clients if str(name) != removed) if isinstance(clients, Mapping) else []
    default = config.get("DEFAULT")
    if not isinstance(default, Mapping):
        return []

    updates: list[tuple[list[str], object | None]] = []
    if default.get("default_torrent_client") == removed:
        updates.append((["DEFAULT", "default_torrent_client"], remaining[0] if remaining else None))
    for key in ("injecting_client_list", "searching_client_list"):
        value = default.get(key)
        if isinstance(value, list) and removed in value:
            filtered = [item for item in value if item != removed]
            updates.append((["DEFAULT", key], filtered if filtered else None))
    return updates

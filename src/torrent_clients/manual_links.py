"""Prepare tracker payload links locally without constructing a client connection."""

import os
import platform
from pathlib import Path
from typing import Any

from torf import Torrent

from src.meta import Meta
from src.torrent_clients.link_paths import qbit_link_target
from src.torrent_clients.path_utils import coerce_str_list, tracker_directory
from src.torrent_clients.qbittorrent import _link_torrent_files, async_link_directory


def selected_clients(meta: Meta, config: dict[str, Any]) -> list[str]:
    if meta.client == "none" or meta.no_seed:
        return []
    if meta.client:
        return [meta.client]
    defaults = config.get("DEFAULT", {})
    clients = coerce_str_list(defaults.get("injecting_client_list", []))
    return clients or coerce_str_list(defaults.get("default_torrent_client", []))


def rtorrent_link_target(src: str, client: dict[str, Any]) -> Path:
    folders = coerce_str_list(client.get("linked_folder", []))
    drive = os.path.splitdrive(src)[0] if platform.system() == "Windows" else "/"
    if platform.system() != "Windows":
        root = "/" + src.strip("/").split("/")[0]
        if any(root in folder or folder in root for folder in folders):
            drive = root
    for folder in folders:
        if (platform.system() == "Windows" and os.path.splitdrive(folder)[0] == drive) or (
            platform.system() != "Windows" and (src.startswith(folder) or folder.startswith(src) or folder.startswith(drive))
        ):
            return Path(folder)
    if client.get("linking") == "symlink" and folders:
        return Path(folders[0])
    raise ValueError("No suitable linked folder found for rTorrent")


async def prepare_manual_links(meta: Meta, config: dict[str, Any], torrent_path: Path) -> list[str]:
    """Use injection layout rules, but fail closed on collisions or failed links."""
    if not meta.path:
        raise ValueError("Manual payload source path is missing")
    torrent = Torrent.read(torrent_path)
    source = Path(meta.path)
    source_root = source if source.is_dir() else source.parent
    paths: list[str] = []
    for name in selected_clients(meta, config):
        if name == "none":
            continue
        client = config.get("TORRENT_CLIENTS", {}).get(name)
        if not isinstance(client, dict):
            raise ValueError(f"Torrent client {name!r} not found in config")
        kind = str(client.get("torrent_client", "")).lower()
        if kind not in {"qbit", "rtorrent"} or client.get("linking") not in {"hardlink", "symlink"}:
            continue
        src = source
        if torrent.mode == "singlefile" and len(meta.filelist) == 1 and Path(meta.filelist[0]).is_file():
            src = Path(meta.filelist[0])
        target = await qbit_link_target(str(src), client) if kind == "qbit" else rtorrent_link_target(str(src), client)
        if target is None:
            raise ValueError("Manual payload link target is unavailable")
        tracker_cfg = config.get("TRACKERS", {}).get("HDBITS", {})
        tracker_dir = tracker_directory(target, str(tracker_cfg.get("link_dir_name", "")).strip(), "HDBITS")
        # An existing tracker directory must not redirect writes outside the chosen root.
        if not tracker_dir.resolve().is_relative_to(target.resolve()):
            raise ValueError("Manual tracker directory escapes the configured linked folder")
        hardlink = client["linking"] == "hardlink"
        if torrent.mode == "multifile":
            for file in torrent.files:
                relative = Path(str(file)).relative_to(torrent.name)
                item = source_root / relative
                if not item.resolve().is_relative_to(source_root.resolve()) or not item.is_file() or item.stat().st_size != file.size:
                    raise ValueError("Manual torrent does not match the source payload")
            linked = await _link_torrent_files(torrent, source_root, tracker_dir, hardlink)
            payload = tracker_dir / torrent.name
        else:
            if src.name != torrent.name or not src.is_file() or src.stat().st_size != torrent.size:
                raise ValueError("Manual torrent does not match the source payload")
            payload = tracker_dir / src.name
            if not payload.parent.resolve().is_relative_to(tracker_dir.resolve()):
                raise ValueError("Manual payload path escapes the tracker directory")
            if (payload.exists() or payload.is_symlink()) and (not payload.exists() or not src.samefile(payload)):
                raise ValueError(f"Manual payload destination contains a different file: {payload}")
            linked = await async_link_directory(str(src), payload, hardlink)
        if not linked:
            raise ValueError("Manual payload linking failed; no client registration attempted")
        paths.append(str(payload))
    return list(dict.fromkeys(paths))

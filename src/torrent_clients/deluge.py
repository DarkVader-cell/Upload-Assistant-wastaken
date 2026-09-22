# Upload Assistant © 2025 Audionut & wastaken7 — Licensed under UAPL v1.0
import base64
import threading
from pathlib import Path
from typing import Any

from deluge_client import DelugeRPCClient
from torf import Torrent

from src.console import logger
from src.torrent_clients.path_utils import map_save_path


# Deluge's RPC protocol is request/response oriented. Serialise add operations
# so concurrent Upload Assistant jobs cannot interleave responses on the remote
# daemon, matching the dedicated Autobrr Deluge client behaviour.
_deluge_action_lock = threading.Lock()


class DelugeClientMixin:
    def deluge(self, path: str, torrent_path: str, torrent: Torrent, local_path: str, remote_path: str, client: dict[str, Any]) -> None:
        # Use a fresh client per action and a longer RPC read/write timeout. The
        # custom Whatbox Deluge instance can take longer to answer while it is
        # handling race traffic; the default deluge-client timeout is 20s.
        with _deluge_action_lock:
            deluge_client: Any = DelugeRPCClient(
                client["deluge_url"],
                int(client["deluge_port"]),
                client["deluge_user"],
                client["deluge_pass"],
                timeout=60,
            )
            try:
                deluge_client.connect()
                if deluge_client.connected:
                    logger.info("Connected to Deluge")
                    # Remote path mount
                    path = map_save_path(path, local_path, remote_path, trailing_slash=False)
                    path = Path(path).parent.as_posix()
                    deluge_client.call(
                        "core.add_torrent_file",
                        torrent_path,
                        base64.b64encode(torrent.dump()),
                        {"download_location": path, "seed_mode": True},
                    )
                    logger.debug(f"[cyan]Path: {path}")
                else:
                    logger.info("[bold red]Unable to connect to deluge")
            finally:
                if getattr(deluge_client, "connected", False):
                    deluge_client.disconnect()

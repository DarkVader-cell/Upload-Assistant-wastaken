"""Filesystem-only selection of qBittorrent link roots."""

import asyncio
import os
import platform
import subprocess
from pathlib import Path
from typing import Any

from src.console import logger
from src.torrent_clients.path_utils import coerce_str_list


async def qbit_link_target(src: str, client: dict[str, Any]) -> Path | None:
    use_symlink = client.get("linking") == "symlink"
    use_hardlink = client.get("linking") == "hardlink"
    # Get linked folder for this drive
    linked_folder = coerce_str_list(client.get("linked_folder", []))
    logger.debug(f"Linked folders: {linked_folder}")

    # Determine drive letter (Windows) or root (Linux)
    src_drive: str
    if platform.system() == "Windows":
        src_drive = os.path.splitdrive(src)[0]
    else:
        # On Unix/Linux, use the full mount point path for more accurate matching
        src_drive = "/"

        # Get all mount points on the system to find the most specific match
        mounted_volumes: list[str] = []
        try:
            # Read mount points from /proc/mounts or use 'mount' command output
            if Path("/proc/mounts").exists():
                mounts_text = await asyncio.to_thread(Path("/proc/mounts").read_text)
                for line in mounts_text.splitlines():
                    parts = line.split()
                    if len(parts) >= 2:
                        mount_point = parts[1]
                        mounted_volumes.append(mount_point)
            else:
                # Fall back to mount command if /proc/mounts doesn't exist
                output = str(await asyncio.to_thread(subprocess.check_output, ["mount"], text=True))
                for line in output.splitlines():
                    parts = line.split()
                    if len(parts) >= 3:
                        mount_point = parts[2]
                        mounted_volumes.append(mount_point)
        except Exception as e:
            logger.debug(f"[yellow]Error getting mount points: {e!s}")

        # Sort mount points by length (descending) to find most specific match first
        mounted_volumes.sort(key=len, reverse=True)

        # Find the most specific mount point that contains our source path
        for mount_point in mounted_volumes:
            if src.startswith(mount_point):
                src_drive = mount_point
                logger.debug(f"[cyan]Found mount point: {mount_point} for path: {src}")
                break

        # If we couldn't find a specific mount point, fall back to linked folder matching
        if src_drive == "/":
            # Extract the first directory component for basic matching
            src_parts = src.strip("/").split("/")
            if src_parts:
                src_root_dir = "/" + src_parts[0]
                # Check if any linked folder contains this root
                for folder in linked_folder:
                    if src_root_dir in folder or folder in src_root_dir:
                        src_drive = src_root_dir
                        break

    # Find a linked folder that matches the drive
    link_target: str | None = None
    if platform.system() == "Windows":
        # Windows matching based on drive letters
        for folder in linked_folder:
            folder_drive = os.path.splitdrive(folder)[0]
            if folder_drive == src_drive:
                link_target = folder
                break
    else:
        # Unix/Linux matching based on path containment
        for folder in linked_folder:
            # Check if the linked folder starts with the mount point
            if folder.startswith(src_drive) or src.startswith(folder):
                link_target = folder
                break

            # Also check if this is a sibling mount point with the same structure
            folder_parts = folder.split("/")
            src_drive_parts = src_drive.split("/")

            # Check if both are mounted under the same parent directory
            if len(folder_parts) >= 2 and len(src_drive_parts) >= 2 and folder_parts[1] == src_drive_parts[1]:
                potential_match = Path(src_drive) / folder_parts[-1]
                if Path(potential_match).exists():
                    link_target = potential_match
                    logger.debug(f"[cyan]Found sibling mount point linked folder: {link_target}")
                    break

    logger.debug(f"Source drive: {src_drive}")
    logger.debug(f"Link target: {link_target}")
    # If using symlinks and no matching drive folder, allow any available one
    if use_symlink and not link_target and linked_folder:
        link_target = linked_folder[0]

    if (use_symlink or use_hardlink) and not link_target:
        error_msg = f"No suitable linked folder found for drive {src_drive}"
        logger.info(f"[bold red]{error_msg}")
        raise ValueError(error_msg)

    return Path(link_target) if link_target is not None else None

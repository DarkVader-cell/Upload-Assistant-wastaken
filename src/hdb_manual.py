"""Local HDBits torrent preparation; no tracker or client registration."""

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from torf import Torrent

from src.meta import Meta
from src.torrent_clients.manual_links import prepare_manual_links
from src.trackers.common import Common
from src.trackers.hdbits import HDBits

PLACEHOLDER_ANNOUNCE = "https://hdbits.invalid/announce"


def validate_manual_options(meta: Meta) -> None:
    if any((meta.hdb_offer, meta.usenet, meta.site_upload, meta.site_upload_queue, meta.site_check,
            meta.manual, meta.debug, meta.delete_tmp, meta.prepare_only, meta.dry_run_plan,
            meta.cleanup, meta.comparison)):
        raise ValueError("--hdb-manual cannot be combined with --hdb-offer, Usenet, site actions, --manual, debug, delete-tmp, prepare-only, plan, cleanup or comparisons")
    if meta.get_tracker_id("HDBITS"):
        raise ValueError("--hdb-manual cannot use an HDBITS metadata reference (no HDB API access)")
    from src.trackersetup import tracker_class_map

    if "MANUAL" in meta.trackers:
        raise ValueError("--hdb-manual cannot be combined with the MANUAL package tracker")
    if any(t == "USENET" or getattr(tracker_class_map.get(t), "is_usenet", False) for t in meta.trackers):
        raise ValueError("--hdb-manual cannot be combined with Usenet indexers")


def select_manual_trackers(meta: Meta) -> None:
    """Never inherit default remote upload targets for a manual-only invocation."""
    trackers = meta.trackers.split(",") if isinstance(meta.trackers, str) else meta.trackers
    meta.trackers = list(dict.fromkeys(Meta.canonical_tracker_name(t.strip()) for t in trackers if t.strip()))
    if "HDBITS" not in meta.trackers:
        meta.trackers.append("HDBITS")


def has_manual_target(meta: Meta) -> bool:
    return meta.hdb_manual and "HDBITS" in meta.trackers


def allow_manual_after_failed_threshold(meta: Meta) -> bool:
    """Keep local preparation independent without allowing any remote uploads."""
    if not has_manual_target(meta):
        return False
    for tracker, status in meta.tracker_status.items():
        if tracker != "HDBITS":
            status["upload"] = False
    return True


def manual_announce(config: dict[str, Any]) -> str:
    value = str(config.get("TRACKERS", {}).get("HDBITS", {}).get("announce_url") or "").strip()
    if not value or any(c in value for c in "<> "):
        return PLACEHOLDER_ANNOUNCE
    parsed = urlsplit(value)
    # Only an explicitly configured HDB tracker URL is usable; never inherit BASE's announce.
    if parsed.scheme not in {"http", "https"} or parsed.hostname != "tracker.hdbits.org" or parsed.username or parsed.password:
        return PLACEHOLDER_ANNOUNCE
    return value


async def prepare_hdb_manual(meta: Meta, config: dict[str, Any]) -> Path:
    announce = manual_announce(config)
    common = Common(config)
    base = await common.get_base_torrent_path(meta, "HDBITS", config.get("TRACKERS", {}).get("HDBITS", {}))
    if base is None or not Path(base).is_file():
        raise FileNotFoundError("HDBITS: no policy-compliant base torrent is available")
    output = Path(meta.base_dir) / "tmp" / meta.uuid / "[HDBITS].torrent"
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Refusing to overwrite existing manual torrent: {output}; move it aside before retrying")
    await common.create_torrent_for_upload(meta, "HDBITS", HDBits.source_flag, announce_url=announce)
    prepared = Torrent.read(output)
    if prepared.metainfo["info"].get("private") != 1:
        prepared.private = True
        prepared.write(output, overwrite=True)
    paths = await prepare_manual_links(meta, config, output)
    status = meta.tracker_status.setdefault("HDBITS", {})
    status.update(upload=False, upload_success=None, manual_pending=False, manual_prepared=True,
                  manual_torrent_path=str(output), manual_payload_paths=paths,
                  status_message="Manual torrent prepared locally; not uploaded or seeded")
    print(f"HDBITS manual torrent: {output}")
    if announce == PLACEHOLDER_ANNOUNCE:
        print("Uses non-routable placeholder announce https://hdbits.invalid/announce; do not seed this torrent.")
    for path in paths:
        print(f"HDBITS prepared payload: {path}")
    print("Upload [HDBITS].torrent manually to the approved HDBits form. Re-download the final site torrent with your real announce before adding it to your client and seeding. UA has not uploaded or registered this torrent.")
    return output

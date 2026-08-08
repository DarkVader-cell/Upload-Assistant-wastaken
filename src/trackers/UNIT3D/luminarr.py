# Upload Assistant © 2025 Audionut & wastaken7 — Licensed under UAPL v1.0
import re
from typing import Any

import cli_ui

from src.console import logger
from src.meta import Meta
from src.rehostimages import ImageHostPolicy, RehostImagesManager
from src.trackers.common import Common
from src.trackers.UNIT3D import UNIT3D


class Luminarr(UNIT3D):
    """
    Luminarr is a Private Torrent Tracker for MOVIES / TV
    """

    tracker = "LUMINARR"
    display_name = "Luminarr"
    allows_bloated_audio = True
    base_url = "https://luminarr.me"
    approved_image_hosts = ("imgbox", "imgbb", "onlyimage", "ptscreens", "passtheimage")
    image_host_policy = ImageHostPolicy(
        {"ibb.co": "imgbb", "imgbox.com": "imgbox", "onlyimage.org": "onlyimage", "ptscreens.com": "ptscreens", "img.passtheima.ge": "passtheimage"},
        approved_image_hosts,
    )
    banned_groups: tuple[str, ...] = ()
    id_url = f"{base_url}/api/torrents/"
    upload_url = f"{base_url}/api/torrents/upload"
    requests_url = f"{base_url}/api/requests/filter"
    search_url = f"{base_url}/api/torrents/filter"
    torrent_url = f"{base_url}/torrents/"
    supported_categories = ("TV", "MOVIE")
    tracker_urls = ("https://luminarr.me",)

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config, tracker_name="LUMINARR")
        self.config = config
        self.common = Common(config)
        self.rehost_images_manager = RehostImagesManager(config)

    @staticmethod
    def _encoder_family(meta: Meta) -> str:
        """Return the evidenced x264/x265 encoder family, not only the codec."""
        evidence = [str(meta.video_encode or "")]
        tracks = meta.mediainfo.get("media", {}).get("track", []) if isinstance(meta.mediainfo, dict) else []
        if isinstance(tracks, dict):
            tracks = [tracks]
        for track in tracks if isinstance(tracks, list) else []:
            if isinstance(track, dict) and track.get("@type") == "Video":
                evidence.extend(str(track.get(key) or "") for key in ("Encoded_Library", "Encoded_Library_Name"))
        normalized = " ".join(evidence).lower()
        if "x265" in normalized:
            return "x265"
        if "x264" in normalized:
            return "x264"
        return ""

    @staticmethod
    def _is_live_action(meta: Meta) -> bool:
        descriptors = [*meta.genres, *meta.keywords]
        return not meta.anime and not any("animation" in str(value).casefold() for value in descriptors)

    def _accepted_encode(self, meta: Meta) -> tuple[bool, str]:
        if meta.is_disc or str(meta.type or "").upper() != "ENCODE":
            return True, ""
        match = re.search(r"(\d{3,4})", str(meta.resolution or ""))
        height = int(match.group(1)) if match else 0
        encoder = self._encoder_family(meta)
        if height and height < 1080 and encoder != "x264":
            return False, "resolutions below 1080p must use x264"
        if str(meta.resolution or "").casefold() != "1080p" or not self._is_live_action(meta):
            return True, ""
        is_hdr = any(marker in str(meta.hdr or "").upper() for marker in ("HDR", "DV", "HLG"))
        required = "x265" if is_hdr else "x264"
        if encoder != required:
            return False, f"1080p {'HDR' if is_hdr else 'SDR'} live-action encodes must use {required}"
        return True, ""

    async def get_additional_data(self, meta: Meta) -> dict[str, Any]:
        return {
            "mod_queue_opt_in": await self.get_flag(meta, "modq"),
        }

    async def get_additional_checks(self, meta: Meta) -> bool:
        accepted_encode, reason = self._accepted_encode(meta)
        if not accepted_encode:
            logger.info(f"{self.tracker}: [bold red]{reason}.[/bold red]")
            return False

        if meta.is_disc not in ["BDMV", "DVD"] and not await self.common.check_language_requirements(
            meta, self.tracker, languages_to_check=["english"], check_audio=True, check_subtitle=True, original_language=True
        ):
            return False

        if meta.is_disc not in ["BDMV", "DVD"] and meta.resolution not in ["8640p", "4320p", "2160p", "1440p", "1080p", "1080i", "720p"]:
            if not meta.unattended or (meta.unattended and meta.unattended_confirm):
                logger.info(f"{self.tracker}: [bold red]only allows SD releases when the content does not have a higher resolution release.[/bold red]")
                if cli_ui.ask_yes_no("Do you want to upload anyway?", default=False):
                    pass
                else:
                    return False
            else:
                return False

        if not meta.is_disc and meta.container != "mkv":
            logger.info(f"{self.tracker}: [bold red]only allows MKV containers for non-disc uploads.[/bold red]")
            return False

        if not meta.valid_mi_settings:
            logger.info(f"{self.tracker}: [bold red]No encoding settings in mediainfo, skipping {self.tracker} upload.[/bold red]")
            return False

        return self.common.check_and_confirm_adult_media_upload(meta, self.tracker)

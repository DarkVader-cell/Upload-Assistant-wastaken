# Upload Assistant © 2025 Audionut & wastaken7 — Licensed under UAPL v1.0
from typing import Any, cast

from src.console import logger
from src.languages import languages_manager
from src.meta import Meta
from src.rehostimages import ImageHostPolicy, RehostImagesManager
from src.trackers.common import Common
from src.trackers.UNIT3D import UNIT3D


class Aither(UNIT3D):
    """
    Aither is a Private Torrent Tracker for HD MOVIES / TV
    """

    tracker = "AITHER"
    display_name = "Aither"
    base_url = "https://aither.cc"
    approved_image_hosts = ("imgbox", "imgbb", "onlyimage", "ptscreens", "passtheimage")
    image_host_policy = ImageHostPolicy(
        {"ibb.co": "imgbb", "imgbox.com": "imgbox", "onlyimage.org": "onlyimage", "ptscreens.com": "ptscreens", "img.passtheima.ge": "passtheimage"},
        approved_image_hosts,
    )
    banned_groups: tuple[str, ...] = ()
    banned_url = f"{base_url}/api/blacklists/releasegroups"
    claims_url = f"{base_url}/api/internals/claim"
    id_url = f"{base_url}/api/torrents/"
    upload_url = f"{base_url}/api/torrents/upload"
    search_url = f"{base_url}/api/torrents/filter"
    torrent_url = f"{base_url}/torrents/"
    requests_url = f"{base_url}/api/requests/filter"
    trumping_url = f"{base_url}/api/trumping-reports/filter"
    supported_categories = ("TV", "MOVIE")
    tracker_urls = ("https://aither.cc",)
    allowed_bloated_audio_languages = ("en",)

    def __init__(self, config: dict[str, Any]):
        super().__init__(config, tracker_name="AITHER")
        self.rehost_images_manager = RehostImagesManager(config)
        self.config = config
        self.common = Common(config)

    async def get_additional_checks(self, meta: Meta):
        should_continue = True

        if meta.is_disc not in ["BDMV", "DVD"] and not await self.common.check_language_requirements(
            meta, self.tracker, languages_to_check=["english"], check_audio=True, check_subtitle=True, original_language=True, original_required=True
        ):
            return False

        if meta.valid_mi is False:
            logger.info(f"{self.tracker}: [bold red]No unique ID in mediainfo, skipping {self.tracker} upload.")
            return False

        if not self._audio_tracks_allowed(meta):
            return False

        return should_continue

    def _audio_tracks_allowed(self, meta: Meta) -> bool:
        """Reject duplicate primary audio languages unless marked compatible."""
        mediainfo = cast(dict[str, Any], meta.mediainfo or {})
        media = cast(dict[str, Any], mediainfo.get("media") or {})
        tracks = cast(list[dict[str, Any]], media.get("track") or [])

        tracks_by_language: dict[str, list[dict[str, Any]]] = {}
        for track in tracks:
            if track.get("@type") != "Audio":
                continue
            title = str(track.get("Title") or track.get("title") or "").lower()
            if "commentary" in title:
                continue
            language = str(track.get("Language") or "und").strip().lower()
            tracks_by_language.setdefault(language, []).append(track)

        for language, language_tracks in tracks_by_language.items():
            if len(language_tracks) <= 1:
                continue
            primary_tracks = [track for track in language_tracks if "compatibility" not in str(track.get("Title") or track.get("title") or "").lower()]
            if len(primary_tracks) > 1:
                logger.info(
                    f"{self.tracker}: [bold red]Found {len(primary_tracks)} audio tracks in the same language "
                    f"({language or 'unknown'}) without a Compatibility label.[/bold red]"
                )
                return False

        return True

    async def get_additional_data(self, meta: Meta):
        hdr_value = meta.hdr or ""
        has_hdr10p = "HDR10+" in hdr_value

        data: dict[str, Any] = {
            "mod_queue_opt_in": await self.get_flag(meta, "modq"),
        }
        if "DV" in hdr_value:
            data["dv"] = 1
        if has_hdr10p:
            data["hdr10p"] = 1
        elif not has_hdr10p and any(flag in hdr_value for flag in ["HDR", "HLG"]):
            data["hdr"] = 1

        return data

    async def get_name(self, meta: Meta):
        aither_name: str = meta.name
        resolution: str = meta.resolution
        video_codec: str = meta.video_codec
        video_encode: str = meta.video_encode
        name_type: str = meta.type or ""
        source: str = meta.source or ""
        alt_title = meta.aka if not meta.no_aka else ""

        year = str(meta.year) if meta.year is not None else ""
        if meta.category == "TV":
            year = str(meta.year) if (meta.year is not None and meta.search_year != "") else ""
        manual_year_value = str(meta.manual_year)
        if manual_year_value and int(manual_year_value) > 0:
            year = manual_year_value
        if meta.no_year:
            year = ""

        if not meta.language_checked:
            await languages_manager.process_desc_language(meta, tracker=self.tracker)
        audio_languages: list[str] = [] if not meta.audio_languages else meta.audio_languages
        if audio_languages and not await languages_manager.has_english_language(audio_languages):
            foreign_lang = audio_languages[0].upper()
            if name_type == "REMUX" and source in ("PAL DVD", "NTSC DVD", "DVD"):
                if year:
                    aither_name = aither_name.replace(year, f"{year} {foreign_lang}", 1)
            elif meta.is_disc != "BDMV":
                aither_name = aither_name.replace(meta.resolution, f"{foreign_lang} {meta.resolution}", 1)

        if name_type == "DVDRIP":
            source = "DVDRip"
            aither_name = aither_name.replace(f"{meta.source} ", "", 1)
            aither_name = aither_name.replace(f"{meta.video_encode}", "", 1)
            aither_name = aither_name.replace(f"{source}", f"{resolution} {source}", 1)
            aither_name = aither_name.replace((meta.audio), f"{meta.audio}{video_encode}", 1)

        elif meta.is_disc == "DVD" or (name_type == "REMUX" and source in ("PAL DVD", "NTSC DVD", "DVD")):
            aither_name = aither_name.replace(meta.source or "", f"{resolution} {meta.source}", 1)
            aither_name = aither_name.replace((meta.audio), f"{video_codec} {meta.audio}", 1)

        if meta.trump_reason == "exact_match":
            aither_name = aither_name + " - TRUMP"

        if alt_title:
            aither_name = aither_name.replace(f"{year} {alt_title}", f"{alt_title} {year}", 1)

        return {"name": aither_name}

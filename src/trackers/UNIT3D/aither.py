# Upload Assistant © 2025 Audionut & wastaken7 — Licensed under UAPL v1.0
import re
from typing import Any, cast

import langcodes

from src.console import logger
from src.meta import Meta
from src.rehostimages import ImageHostPolicy, RehostImagesManager
from src.trackers.common import Common
from src.trackers.naming import BLU_EDITION_TERMS, VideoNameRules, add_incomplete_pack_marker, build_video_name
from src.trackers.UNIT3D import UNIT3D

# Aither keeps editions (Criterion, Remastered, Anniversary...) in the description; cuts stay in the title.
AITHER_EDITION_TERMS = re.compile(
    rf"{BLU_EDITION_TERMS.pattern}|\brestored\b|\bmultiple(?:\s+languages)?\b",
    re.IGNORECASE,
)
AITHER_NAME_RULES = VideoNameRules(
    language_slot="before_cut",
    english_dub_only=True,
    edition_terms=AITHER_EDITION_TERMS,
    dvd_resolution=True,
    dvd_video_codec=True,
    three_d_slot="source_on_discs",
    honor_manual_year_on_tv=True,
)


class Aither(UNIT3D):
    """
    Aither is a Private Torrent Tracker for HD MOVIES / TV

    API spec: https://aither.cc/pages/api
    Synced with: last edited October 19, 2026.
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

    async def get_category_id(self, meta: Meta, category: str = "", reverse: bool = False, mapping_only: bool = False) -> dict[str, str]:
        category_id = {
            "MOVIE": "1",
            "TV": "2",
            "SPORTS": "9",
        }
        if mapping_only:
            return category_id
        if reverse:
            return {value: key for key, value in category_id.items()}

        resolved_category = "SPORTS" if meta.is_sports else category or meta.category
        return {"category_id": category_id.get(resolved_category, "0")}

    async def get_resolution_id(self, meta: Meta, resolution: str = "", reverse: bool = False, mapping_only: bool = False) -> dict[str, str]:
        # Aither has its own 1440p resolution (id 42) instead of grouping it with 1080p.
        resolution_id = {
            "8640p": "10",
            "4320p": "1",
            "2160p": "2",
            "1440p": "42",
            "1080p": "3",
            "1080i": "4",
            "720p": "5",
            "576p": "6",
            "576i": "7",
            "480p": "8",
            "480i": "9",
        }
        if mapping_only:
            return resolution_id
        if reverse:
            return {value: key for key, value in resolution_id.items()}
        return {"resolution_id": resolution_id.get(resolution or meta.resolution, "10")}

    async def get_season_number(self, meta: Meta) -> dict[str, str]:
        if (await self.get_category_id(meta))["category_id"] != "2":
            return {}
        return await super().get_season_number(meta)

    async def get_episode_number(self, meta: Meta) -> dict[str, str]:
        if (await self.get_category_id(meta))["category_id"] != "2":
            return {}
        return await super().get_episode_number(meta)

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
        """Enforce Aither's original-audio policy, ignoring auxiliary tracks."""
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
            language = self._audio_language_code(track.get("Language"))
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

        # If MediaInfo lacks individual audio tracks (for example a disc), use
        # the already-normalised metadata assembled by the language processor.
        primary_languages = set(tracks_by_language)
        if not primary_languages:
            primary_languages = {self._audio_language_code(language) for language in (meta.audio_languages or [])}
        primary_languages.discard("")
        primary_languages.discard("und")

        original = meta.original_language
        if isinstance(original, list):
            original = original[0] if original else ""
        original_language = self._audio_language_code(original)
        # The common language check establishes the original language in normal
        # uploads.  Do not reject a direct/partial metadata path solely because
        # that upstream lookup has not supplied it yet.
        if not original_language:
            return True
        allowed = {original_language}
        japanese_english_dual = {"en", "ja"}
        if primary_languages and primary_languages not in (allowed, japanese_english_dual):
            logger.info(
                f"{self.tracker}: [bold red]Primary audio must be the original language only, "
                f"or exactly English + Japanese. Found: {', '.join(sorted(primary_languages))}.[/bold red]"
            )
            return False

        return True

    @staticmethod
    def _audio_language_code(value: Any) -> str:
        """Normalise the common MediaInfo/display forms needed by this rule."""
        raw = str(value or "").strip()
        token = raw.lower().replace("_", "-")
        token = token.split("-", 1)[0].split(" ", 1)[0]
        aliases = {
            "english": "en", "eng": "en", "en": "en",
            "japanese": "ja", "jpn": "ja", "jp": "ja", "ja": "ja",
            "undetermined": "und", "undefined": "und",
        }
        if token in aliases:
            return aliases[token]
        try:
            return str(langcodes.Language.get(raw).language or token).lower()
        except (LookupError, ValueError):
            try:
                return str(langcodes.find(raw).language or token).lower()
            except (LookupError, ValueError):
                return token

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

        if await self.get_flag(meta, "refundable") == "1":
            data["refundable"] = "1"

        freeleech_until = meta.get("freeleech_until", 0) or self.tracker_config.get("freeleech_until", 0)
        if freeleech_until:
            try:
                fl_until_val = int(freeleech_until)
                if fl_until_val > 0:
                    data["fl_until"] = fl_until_val
            except ValueError, TypeError:
                pass

        double_upload_until = meta.get("double_upload_until", 0) or self.tracker_config.get("double_upload_until", 0)
        if double_upload_until:
            try:
                du_until_val = int(double_upload_until)
                if du_until_val > 0:
                    data["du_until"] = du_until_val
            except ValueError, TypeError:
                pass

        return data

    async def get_name(self, meta: Meta):
        # A manual --name or a type outside the guide falls back to the generic name.
        aither_name = await build_video_name(meta, AITHER_NAME_RULES, self.tracker) or meta.name
        if meta.trump_reason == "exact_match":
            aither_name = aither_name + " - TRUMP"
        return {"name": add_incomplete_pack_marker(aither_name, meta, self.tracker)}

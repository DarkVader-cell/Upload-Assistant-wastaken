"""PTP coexistence recommendations from the operator-supplied rules snapshot.

Quality, staff approval and screenshot evidence are not inferred from filesize.
"""
from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path

from src.meta import Meta
from src.slot_rules.base import SlotRules, UnknownTraitError, size_diff_ratio
from src.slot_rules.models import SlotDecision, Verdict
from src.slot_rules.profile import (
    DISC,
    DV,
    ENCODE,
    H264,
    H265,
    HDR10,
    HDR10P,
    HDTV,
    REMUX,
    SD,
    WEBDL,
    WEBRIP,
    ReleaseProfile,
    codec_from_text,
    editions_from_text,
    hdr_from_name,
    kind_from_name,
)

CUTS = {"directors", "extended", "uncut", "unrated", "final_cut"}


def ptp_entry(torrent: dict) -> dict:
    """Keep all group data while providing the shared dupe/slot field names."""
    entry = dict(torrent)
    name = str(torrent.get("ReleaseName") or "")
    source = str(torrent.get("Source") or "").lower().replace("-", "")
    codec = str(torrent.get("Codec") or "")
    container = str(torrent.get("Container") or "").lower()
    kind = kind_from_name(name)
    if "remux" in str(torrent.get("RemasterTitle") or "").lower():
        kind = REMUX
    elif container in {"iso", "vob ifo", "vob/ifo", "m2ts"}:
        kind = DISC
    elif source == "web" and kind not in {WEBDL, WEBRIP}:
        kind = WEBRIP if codec.lower() in {"x264", "x265"} else WEBDL
    elif codec.lower() in {"x264", "x265"} and source in {"bluray", "uhd bluray", "hddvd", "dvd", "hdtv"}:
        kind = ENCODE
    entry.update(name=name or f"PTP torrent {torrent.get('Id', 'unknown')}", res=torrent.get("Resolution"),
                 type=kind, size=torrent.get("Size"), media_info=torrent.get("MediaInfo") or "",
                 link=f"https://passthepopcorn.me/torrents.php?torrentid={torrent.get('Id', '')}")
    return entry


def ptp_profile(profile: ReleaseProfile) -> ReleaseProfile:
    """Preserve structured API fields that cannot be guessed from a release name."""
    entry = profile.entry
    edition = editions_from_text(str(entry.get("RemasterTitle") or ""))
    codec = codec_from_text(str(entry.get("Codec") or "")) or profile.codec
    dynamic_text = str(entry.get("RemasterTitle") or "") + " " + str(entry.get("HDR") or "")
    dynamic = hdr_from_name(dynamic_text)
    hdr = (profile.hdr | dynamic) if profile.hdr is not None else (dynamic or None)
    if profile.resolution == "2160p" and not hdr:
        report = str(entry.get("media_info") or entry.get("MediaInfo") or "")
        explicit_sdr = re.search(r"\bSDR\b", profile.name + " " + dynamic_text, re.I) or re.search(r"Color primaries\s*:\s*BT\.709", report, re.I)
        hdr = frozenset() if explicit_sdr else None
    return replace(profile, codec=codec, edition=profile.edition | edition, hdr=hdr)


class PassThePopcornSlotRules(SlotRules):
    TRACKER = "PASSTHEPOPCORN"
    RULES_DATE = date(2026, 10, 19)

    def _upload(self, profile: ReleaseProfile) -> bool:
        return getattr(self, "_candidate", None) is profile

    def _cut(self, profile: ReleaseProfile) -> frozenset[str]:
        if self._upload(profile) and isinstance(self.meta, Meta):
            return editions_from_text(self.meta.edition) & CUTS
        return profile.edition & CUTS

    def _text(self, profile: ReleaseProfile) -> str:
        entry = profile.entry
        if self._upload(profile) and isinstance(self.meta, Meta):
            return " ".join((profile.name, self.meta.edition, json.dumps(self.meta.mediainfo, default=str)))
        return profile.name + " " + " ".join(str(entry.get(k) or "") for k in ("RemasterTitle", "MediaInfo", "media_info"))

    def _dv5(self, profile: ReleaseProfile) -> bool:
        text = self._text(profile)
        if re.search(r"dv(?:he|h1)\.0?5\b|(?:dolby\s*vision|dovi|dv)[ ._-]*profile[ .:_-]*5\b", text, re.I):
            return True
        if profile.hdr and DV in profile.hdr and not ({HDR10, HDR10P} & profile.hdr):
            raise UnknownTraitError("Dolby Vision profile is unknown; do not assume a Profile 5 slot from the DV label alone")
        return False

    def _extras(self, profile: ReleaseProfile) -> bool:
        if self._upload(profile) and isinstance(self.meta, Meta):
            return self.meta.extras is True
        return str(profile.entry.get("NotMainMovie") or "").lower() in {"true", "1", "yes"} or bool(re.search(r"\bextras?\b", str(profile.entry.get("RemasterTitle") or ""), re.I))

    def _open_matte(self, profile: ReleaseProfile) -> bool:
        if self._upload(profile) and isinstance(self.meta, Meta):
            return "open_matte" in editions_from_text(self.meta.edition)
        return "open_matte" in profile.edition

    def _source(self, profile: ReleaseProfile) -> str | None:
        raw = str(profile.entry.get("Source") or "")
        if self._upload(profile) and isinstance(self.meta, Meta):
            raw = str(self.meta.source or raw)
        normalized = re.sub(r"[^a-z]", "", raw.lower())
        if normalized in {"bluray", "uhdbluray"}:
            return "bluray"
        if normalized in {"web", "webdl", "webrip", "hddvd", "hdtv", "dvd"}:
            return normalized
        if raw:
            return None
        if re.search(r"blu[ ._-]?ray", profile.name, re.I):
            return "bluray"
        if re.search(r"\bweb[ ._-]?(?:dl|rip)\b", profile.name, re.I):
            return "web"
        if re.search(r"hd[ ._-]?dvd", profile.name, re.I):
            return "hddvd"
        return None

    def _range(self, profile: ReleaseProfile) -> str:
        hdr = self.require(profile.hdr, "dynamic range")
        if not hdr:
            return "SDR"
        if self._dv5(profile):
            if {HDR10, HDR10P} & hdr:
                raise UnknownTraitError("Profile 5 has no HDR10 base layer; conflicting dynamic-range evidence needs review")
            return "DV Profile 5"
        if {HDR10, HDR10P} & hdr:
            return "HDR10"  # Compatible DV does not create extra HDR10 slots.
        raise UnknownTraitError("Only confirmed SDR, DV Profile 5 or HDR10-compatible UHD slots are defined")

    def _slot(self, profile: ReleaseProfile) -> tuple[object, ...]:
        resolution = self.require(profile.resolution, "resolution")
        kind = self.require(profile.kind, "release type")
        if resolution not in {SD, "720p", "1080p", "2160p"}:
            raise UnknownTraitError("Non-conforming resolution requires a preferred-format exception under rules 3.1-3.3")
        if self._open_matte(profile):
            if resolution != "1080p" or kind not in {ENCODE, WEBRIP}:
                raise UnknownTraitError("The Open Matte exception is for 1080p encodes under Others (4.6.5)")
            return ("Open Matte Others",)
        if self._extras(profile) and kind != DISC:
            return ("Extras", resolution, "Remux" if kind == REMUX else "Encode")
        if kind == WEBDL:
            codec = self.require(profile.codec, "video codec")
            hdr = self.require(profile.hdr, "dynamic range")
            if resolution != "2160p":
                if codec != H264:
                    if resolution != "1080p" or codec != H265:
                        raise UnknownTraitError("This WEB codec needs a preferred-format exception")
                    if hdr:
                        self._range(profile)
                elif hdr:
                    raise UnknownTraitError("HDR WEB requires a preferred-format review")
            if resolution == "2160p":
                dynamic = self._range(profile)
                if codec != H265 and not (dynamic == "SDR" and codec == H264):
                    raise UnknownTraitError("UHD WEB format requires a codec exception")
                return ("WEB-DL", resolution, dynamic)
            return ("WEB-DL", resolution)  # No provider or SD-height split.
        if kind in {DISC, HDTV}:
            if resolution == SD:
                text = str(profile.entry.get("res") or profile.entry.get("Resolution") or profile.name).upper()
                if self._upload(profile) and isinstance(self.meta, Meta):
                    text += " " + self.meta.resolution.upper()
                    height = self.meta.video_height
                    if height == 480:
                        text += " NTSC"
                    elif height == 576:
                        text += " PAL"
                if "NTSC" in text or "480" in text:
                    return ("Untouched DVD", "NTSC")
                if "PAL" in text or "576" in text:
                    return ("Untouched DVD", "PAL")
                raise UnknownTraitError("Untouched SD must identify PAL or NTSC (4.4.1)")
            return ("Untouched", "UHD" if resolution == "2160p" else "HD")
        if kind == REMUX:
            if resolution == SD:
                raise UnknownTraitError("Untouched DVD requires VOB/IFO; an SD MKV remux needs a format exception")
            if resolution == "2160p":
                if profile.hdr is None:
                    raise UnknownTraitError("UHD remux dynamic range is unknown")
                return ("Remux", "UHD", "SDR" if profile.is_sdr else "HDR")
            return ("Remux", "HD")
        if kind not in {ENCODE, WEBRIP, "DVDRIP"}:
            raise UnknownTraitError("Unsupported format needs manual review")
        codec = self.require(profile.codec, "video codec")
        if self._dv5(profile):
            if codec != H265 or resolution not in {"1080p", "2160p"}:
                raise UnknownTraitError("Dolby Vision Profile 5 format needs manual review")
            self._range(profile)
            return ("Profile 5 encode", "UHD" if resolution == "2160p" else "HD")
        if resolution == "2160p":
            if profile.hdr is None:
                raise UnknownTraitError("UHD encode dynamic range is unknown")
            if codec != H265 and not (profile.is_sdr and codec == H264):
                raise UnknownTraitError("UHD encodes require x265; SDR UHD's own slots may use x264 (3.3.3/4.3.1.2)")
            return ("Encode", "2160p", self._range(profile))
        hdr = self.require(profile.hdr, "dynamic range")
        if hdr:
            if resolution != "1080p" or codec != H265 or not hdr & {HDR10, HDR10P}:
                raise UnknownTraitError("HDR10 compatibility/preferred codec is not established for the HD HDR slot")
            return ("HDR x265 encode", "1080p")
        if codec != H264:
            raise UnknownTraitError("SD/HD encode codec is not the preferred x264 format; a format exception needs review")
        if resolution == SD:
            raw_res = str(profile.entry.get("res") or profile.entry.get("Resolution") or profile.name)
            if self._upload(profile) and isinstance(self.meta, Meta):
                raw_res = self.meta.resolution
                source = str(self.meta.source or "").upper()
                if "576" in raw_res and any(x in source for x in ("BLU", "HDTV", "WEB", "HD DVD", "UHD")):
                    return ("HD-sourced 576p",)
            elif "576" in raw_res and str(profile.entry.get("Source") or "").upper() in {"BLU-RAY", "HD-DVD", "HDTV", "WEB"}:
                return ("HD-sourced 576p",)
            return ("SD x264",)
        return ("x264 encode", resolution)

    def _content(self, upload: ReleaseProfile) -> SlotDecision | None:
        if not isinstance(self.meta, Meta):
            return None
        meta = self.meta
        kind = re.sub(r"[^a-z]", "", str(meta.imdb_info.get("type") or "").lower())
        raw_genres = meta.imdb_info.get("genres") or meta.genres or []
        genres = {g.lower() for g in re.findall(r"[A-Za-z]+", raw_genres)} if isinstance(raw_genres, str) else {str(g).lower() for g in raw_genres}
        if "adult" in genres or meta.category == "XXX":
            return self.decision(Verdict.BLOCK, "IMDb Adult/pornographic content is prohibited; disputed tags require staff approval (1.2.3)")
        if meta.category not in {"MOVIE", "TV"}:
            return self.decision(Verdict.BLOCK, "PTP accepts eligible video titles, not this media category")
        if str(meta.type or "").upper() in {"CAM", "TS", "TC", "R5", "DVDSCR", "DCP"} or str(meta.source or "").upper() in {"CAM", "TS", "TC", "R5", "DVDSCR", "DCP"}:
            return self.decision(Verdict.BLOCK, "Pre-retail sources are prohibited (1.2.1)")
        if meta.container.lower().lstrip(".") in {"mp4", "mpeg-4"} or (meta.path and Path(meta.path).suffix.lower() == ".mp4"):
            return self.decision(Verdict.BLOCK, "Remux MP4 to MKV using recent MKVToolNix; do not re-encode (1.2.15)")
        if meta.path and Path(meta.path).suffix.lower() in {".rar", ".zip", ".7z"}:
            return self.decision(Verdict.BLOCK, "Archive/non-video uploads are prohibited (1.2.8)")
        edition = meta.edition.lower()
        if any(x in edition for x in ("ai dub", "ai-generated", "ai generated")):
            return self.decision(Verdict.BLOCK, "Primarily AI-generated titles/dubs are prohibited (1.2.16)")
        if "BRRIP" in {str(meta.source or "").upper(), str(meta.type or "").upper()} or "transcode" in edition:
            return self.decision(Verdict.BLOCK, "Transcodes/BRRips are prohibited; use an untouched source (1.2.11)")
        if "fan edit" in edition or "fanedit" in edition:
            return self.decision(Verdict.BLOCK, "Only official releases, not fan edits, are allowed (1.2.6)")
        series = kind in {"tvseries", "tvepisode"}
        special_series = "documentary" in genres or any(str(k).lower() == "anthology" for k in meta.keywords)
        if series and not special_series:
            return self.decision(Verdict.BLOCK, "Ordinary TV series/episodes are not allowed on PTP (1.2.2)")
        if not meta.imdb_id or str(meta.imdb_id) == "0":
            return self.decision(Verdict.REVIEW, "IMDb is required; titles without an IMDb entry need staff approval (1.1)")
        if kind in {"tvminiseries", "miniseries"}:
            return self.decision(Verdict.REVIEW, "Miniseries require staff approval before uploading (1.1.4)")
        if series:
            return self.decision(Verdict.REVIEW, "Documentary/anthology series require staff approval and correct episode/season packaging (1.1.5-1.1.6)")
        if any(str(k).lower() in {"serial film", "trailer compilation", "filmmaking instructional"} for k in meta.keywords):
            return self.decision(Verdict.REVIEW, "This content type requires staff approval and specific packaging (1.1.9-1.1.10/1.2.7)")
        if kind in {"concert", "comedy", "video"}:
            return self.decision(Verdict.REVIEW, "Confirm an officially released performance: bootlegs, streams and unofficial stand-up are prohibited (1.1.3/1.1.7)")
        if kind not in {"movie", "feature", "tvmovie", "short", "tvshort", "tvspecial"}:
            return self.decision(Verdict.REVIEW, "IMDb content type is unknown or needs eligibility review; confirm allowed content before uploading (1.1)")
        if upload.resolution and meta.video_width and meta.video_height:
            bounds = {SD: ((854, 480) if "480" in meta.resolution else (1024, 576)), "720p": (1280, 720), "1080p": (1920, 1080), "2160p": (4096, 2160)}
            if upload.resolution in bounds and (meta.video_width > bounds[upload.resolution][0] or meta.video_height > bounds[upload.resolution][1]):
                return self.decision(Verdict.REVIEW, "Stored dimensions exceed the selected resolution's maximum; a format exception needs review (3.1-3.3)")
        return None

    @staticmethod
    def _could_share_web_slot(upload: ReleaseProfile, existing: ReleaseProfile) -> bool:
        """Unknown details only matter if this torrent could occupy the WEB slot.

        A bare DV label cannot establish Profile 5, but it does establish that
        the torrent is not SDR. Do not ask for its profile to assess an SDR slot.
        """
        if upload.kind != WEBDL:
            return True
        if existing.kind is not None and existing.kind != WEBDL:
            return False
        if existing.resolution not in {None, "OTHER", upload.resolution}:
            return False
        return not (upload.resolution == "2160p" and upload.is_sdr and bool(existing.hdr))

    def evaluate(self, upload: ReleaseProfile, existing: Sequence[ReleaseProfile]) -> SlotDecision:
        self._candidate = upload
        existing = [ptp_profile(p) for p in existing]
        exact = [p for p in existing if p.exact]
        if exact:
            return self.decision(Verdict.BLOCK, "This exact release is already on PTP", exact)
        content = self._content(upload)
        if content and content.verdict is Verdict.BLOCK:
            return content
        same_cut = [p for p in existing if self._cut(p) == self._cut(upload)]
        web_source = upload.kind in {WEBDL, WEBRIP} or self._source(upload) in {"web", "webdl", "webrip"}
        if web_source and upload.resolution == "2160p" and upload.hdr and upload.hdr & {HDR10, HDR10P}:
            hdr_encodes = [p for p in same_cut if p.resolution == "2160p" and p.kind in {ENCODE, WEBRIP}
                           and p.hdr is not None and bool(p.hdr & {HDR10, HDR10P})]
            bluray_hdr = [p for p in hdr_encodes if self._source(p) == "bluray"]
            if bluray_hdr:
                return self.decision(Verdict.BLOCK, "An HDR Blu-ray UHD encode exists: no further HDR WEB uploads are allowed", bluray_hdr)
            unknown_source = [p for p in hdr_encodes if self._source(p) is None]
            if unknown_source:
                return self.decision(Verdict.REVIEW, "An HDR UHD encode has unknown source; verify the Blu-ray HDR WEB prohibition before uploading", unknown_source)
            uncertain_bluray_hdr = [p for p in same_cut
                                   if p.resolution in {None, "OTHER", "2160p"} and p.kind in {None, ENCODE, WEBRIP}
                                   and p.hdr is None and self._source(p) in {None, "bluray"}]
            if uncertain_bluray_hdr:
                return self.decision(Verdict.REVIEW, "A possible Blu-ray UHD encode has unknown HDR traits; verify the HDR WEB prohibition", uncertain_bluray_hdr)
        try:
            key = self._slot(upload)
            occupants, unknown = [], []
            for profile in same_cut:
                if not self._could_share_web_slot(upload, profile):
                    continue
                try:
                    if self._slot(profile) == key:
                        occupants.append(profile)
                except UnknownTraitError:
                    unknown.append(profile)
            label = " · ".join(str(x) for x in key)
            # Comparison/staff/evidence exceptions never become automatic vacant slots.
            if self._open_matte(upload):
                return self.decision(Verdict.REVIEW, "Open Matte needs OAR comparisons and the Others/Not Main Movie form classification (4.6.5)", occupants, slot=label)
            if upload.kind == WEBDL and upload.resolution == "1080p" and upload.codec == H265 and upload.is_sdr:
                return self.decision(Verdict.REVIEW, "SDR 1080p HEVC WEB-DL needs exhaustive AVC comparisons and superior picture quality, even if AVC is absent (4.2.3)", occupants, slot=label)
            if upload.kind == WEBDL and upload.resolution == SD and any(p.resolution in {"720p", "1080p", "2160p"} for p in same_cut):
                return self.decision(Verdict.BLOCK, "SD WEB-DL may not coexist with an HD equivalent (4.1.3)", same_cut, slot=label)
            if content:
                return self.decision(Verdict.REVIEW, content.reason, same_cut, slot=label)
            # Screenshot tone mapping sets meta.tonemapped: it is NOT evidence that the encode was tone mapped.
            edition = self.meta.edition.lower() if isinstance(self.meta, Meta) else ""
            if upload.kind in {ENCODE, WEBRIP} and ("tonemap" in edition.replace(" ", "").replace("-", "")):
                return self.decision(Verdict.REVIEW, "Tone-mapped encodes need original-source comparisons and confirmation that no retail 4K-remaster HD disc exists (3.2.4)", occupants, slot=label)
            if unknown:
                return self.decision(Verdict.REVIEW, "Some group releases have unknown format/profile traits; slot occupancy cannot be confirmed", [*occupants, *unknown], slot=label)
            capacity = 2 if key[0] in {"x264 encode", "Encode", "SD x264"} else 1
            if key[0] == "SD x264" and any(p.resolution in {"720p", "1080p", "2160p"} or re.search(r"576[pi]?", str(p.entry.get("res") or p.name), re.I) for p in same_cut):
                capacity = 1
            if not occupants:
                return self.decision(Verdict.ALLOW, "No competing release occupies this PTP slot", slot=label,
                                     notes=["Vacancy is not confirmation of release quality, staff approval, subtitle/poster requirements or blacklist status."])
            if len(occupants) >= capacity:
                return self.decision(Verdict.REVIEW, "This PTP slot is occupied; any quality/source/dead/trumpable replacement needs review, not automatic trumping", occupants, slot=label)
            guideline = 0.40 if key[0] == "SD x264" else 0.20
            ratios = [size_diff_ratio(upload, p) for p in occupants]
            details = "unknown" if any(r is None for r in ratios) else ", ".join(f"{r:.0%}" for r in ratios if r is not None)
            return self.decision(Verdict.REVIEW, f"A second encode may coexist only as a distinct retention/quality candidate. Size guideline {guideline:.0%}; observed gap {details}. Size does not establish quality", occupants, slot=label)
        except UnknownTraitError as error:
            return self.decision(Verdict.REVIEW, "PTP slot cannot be determined without manual review", same_cut, why=str(error))

"""HDBits recommendations from operator-supplied 2026-10-19 guidelines.

This is not HD-Torrents. Rights, transparency and source provenance require
human evidence, not a filesize-derived or internal-name-derived approval.
"""
import re
from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path

from src.meta import Meta
from src.slot_rules.base import SlotRules
from src.slot_rules.models import SlotDecision, Verdict
from src.slot_rules.profile import DISC, ENCODE, H264, H265, REMUX, SD, WEBDL, WEBRIP, ReleaseProfile, codec_from_text, resolution_from_name

BANNED = {"cddhd", "eureka", "ddr", "evo", "dnl", "barc0de", "spirit"}
CUTS = {"directors", "extended", "uncut", "unrated", "final_cut", "open_matte"}


class HDBitsSlotRules(SlotRules):
    TRACKER = "HDBITS"
    RULES_DATE = date(2026, 10, 19)

    def decision(self, verdict, reason, conflicts=(), notes=(), *, slot="", why="") -> SlotDecision:
        result = super().decision(verdict, reason, conflicts, notes, slot=slot, why=why)
        result.requires_evidence = verdict is Verdict.REVIEW
        return result

    def review(self, reason, conflicts=(), *, why="") -> SlotDecision:
        result = self.decision(Verdict.REVIEW, reason, conflicts, why=why)
        result.notes.append("Also verify applicable lottery/signup rights, source/demux/conversion logs, audio/dub/forced-subtitle rules and screenshot coverage. These are not inferred from names or filesize.")
        return result

    def evaluate(self, upload: ReleaseProfile, existing: Sequence[ReleaseProfile]) -> SlotDecision:
        meta = self.meta if isinstance(self.meta, Meta) else None
        if meta and meta.category in {"BOOK", "GAME", "APP"}:
            return self.decision(Verdict.BLOCK, "This content category is not eligible HDBits video/audio content")
        existing = [replace(p, resolution=(resolution_from_name(p.name) or p.resolution) if p.resolution in {None, "OTHER"} else p.resolution,
                            codec=codec_from_text(str(p.entry.get("codec") or "")) or p.codec) for p in existing]
        same = [p for p in existing if (p.edition & CUTS) == (upload.edition & CUTS) and p.is_3d == upload.is_3d]
        if any(p.exact for p in existing):
            return self.decision(Verdict.BLOCK, "This exact release is already on HDBits", [p for p in existing if p.exact])
        if upload.kind in {ENCODE, WEBRIP} and (upload.group or "").lower() in BANNED:
            return self.decision(Verdict.BLOCK, "This encode group is prohibited by the supplied HDBits rules")
        if upload.resolution == "720p" and upload.hdr and upload.kind in {ENCODE, WEBRIP, WEBDL}:
            return self.decision(Verdict.BLOCK, "720p HDR encodes/WEB-DL are not allowed")
        if meta:
            suffix = Path(meta.path or "").suffix.lower()
            if suffix in {".rar", ".zip", ".7z"}:
                return self.decision(Verdict.BLOCK, "Archived/RAR content is not allowed")
            iso = suffix == ".iso" or meta.container.lower() == "iso"
            if upload.kind == DISC and iso and not upload.is_3d:
                return self.decision(Verdict.BLOCK, "Non-3D Blu-ray/HD DVD ISO images are not allowed")
            if upload.kind == DISC and upload.is_3d and not iso:
                return self.review("3D Blu-rays must be supplied as ISO images, not extracted disc folders")
            if re.search(r"\bBD[ ._-]?[59]\b", meta.disctype or "", re.I):
                return self.decision(Verdict.BLOCK, "BD5/BD9 releases are prohibited")
            if meta.get("publicly_available") is True:
                return self.decision(Verdict.BLOCK, "Publicly/freely downloadable WEB content is prohibited")
            if meta.get("has_muxed_dubs") is True and meta.get("is_animation") is False and upload.kind in {ENCODE, WEBRIP, REMUX, WEBDL}:
                return self.decision(Verdict.BLOCK, "Muxed dubs are prohibited for non-animated encodes/WEB-DL/remuxes")
            if meta.get("HDBITS_missing_forced_subtitles") is True:
                return self.decision(Verdict.BLOCK, "Required forced subtitles for foreign speech must be muxed and set as default")
            if meta.get("payload_modified") is True and meta.get("filename_changed") is False:
                return self.decision(Verdict.BLOCK, "A modified encode/WEB/remux must use a different filename to avoid seeding issues")
            source = str(meta.source or "").upper()
            if source in {"CAM", "TS", "TC", "R5", "DVDSCR", "SCREENER"}:
                return self.decision(Verdict.BLOCK, "Screeners, camera/prerelease and low-quality R5 sources are prohibited")
            if source in {"BRRIP", "BDRIP-REENCODE"} or meta.get("reencoded_from_encode") is True:
                return self.decision(Verdict.BLOCK, "Re-encodes of existing encodes are prohibited")
            edition = meta.edition.lower()
            if "custom" in edition and upload.kind == DISC:
                return self.decision(Verdict.BLOCK, "Custom HD DVD/Blu-ray discs are prohibited")
            if "trailer" in edition or "preview" in edition:
                return self.decision(Verdict.BLOCK, "Trailers/previews are prohibited")
            tracks = (meta.mediainfo or {}).get("media", {}).get("track", [])
            audio = [t for t in tracks if isinstance(t, dict) and t.get("@type") == "Audio"]
            for track in audio:
                title = str(track.get("Title") or "")
                service = str(track.get("ServiceKind") or track.get("ServiceKind/String") or "")
                if re.search(r"audio descript|descriptive audio|visually impaired", title + " " + service, re.I) or service.upper() == "VI":
                    return self.decision(Verdict.BLOCK, "Muxed descriptive audio tracks are prohibited on HDBits")
            if meta.category == "TV":
                if meta.tv_pack and re.search(r"S\d+\s*[-+]\s*S?\d+", meta.season or "", re.I):
                    return self.decision(Verdict.BLOCK, "Multi-season TV packs are prohibited; upload seasons separately")
                if not meta.tv_pack and meta.get("HDBITS_torrent_has_episode_folder") is True:
                    return self.decision(Verdict.BLOCK, "Single TV episodes must be folderless torrents")
                return self.review("Verify TV signup/48-hour rights and packing requirements before uploading", why="Completed/all-at-once WEB-DL/external WEBRip seasons must be packed. Weekly final episode comes before the pack; retain original episode filenames, no subfolders/samples/NFOs. Do not delete individual episodes yourself.")
            if meta.category in {"MUSIC", "AUDIO"}:
                return self.review("Verify MKA audio-track eligibility or professionally mastered/released 4.0+ music; no stereo upmix or copy protection")
            if meta.category == "XXX":
                return self.review("Porn-site videos require at least one month's content per pack; single videos are prohibited")
            if meta.get("upscaled") is True:
                return self.review("Upscales need a qualifying high-quality anime or lossless-multichannel concert exception")
        if upload.resolution == SD:
            return self.review("SD/upscaled material is prohibited except qualifying anime or multichannel concerts; verify an exception")
        if upload.resolution not in {"720p", "1080p", "2160p"} and upload.kind != DISC:
            return self.review("The selected HD resolution is unknown or needs an eligibility exception")
        if upload.is_3d and upload.kind != DISC:
            return self.review("Verify 3D video is side-by-side or frame sequential and meets its source/category rules")
        if upload.kind == WEBDL and upload.codec not in {H264, H265}:
            return self.review("Verify the untouched WEB video codec and restricted source provenance")
        if upload.resolution in {"720p", "1080p"} and upload.kind in {ENCODE, WEBRIP, WEBDL} and (upload.codec == H265 or (upload.codec == H264 and upload.hi10p)):
            return self.review("HD HEVC/10-bit AVC requires exhaustive proof against 8-bit AVC: better quality or at least 20% bitrate reduction at the same picture quality", why="Filesize differences alone do not prove either requirement.")
        unknown = [p for p in same if p.kind is None or (p.kind == upload.kind and p.resolution in {None, "OTHER"})]
        if unknown:
            return self.review("Some potentially competing HDBits releases have unknown format/resolution traits; verify occupancy", unknown)
        competitors = [p for p in same if p.resolution == upload.resolution and p.kind == upload.kind]
        web = [p for p in same if p.kind == WEBDL]
        encodes = [p for p in same if p.kind in {ENCODE, WEBRIP}]
        def dead(p):
            return p.entry.get("dead") is True
        if upload.kind == REMUX:
            return self.review("Verify remux lottery/in-progress rights and source/demux/mux/audio/subtitle evidence", competitors,
                               why="Remux rights expire after the stated 48 hours, not from an inferred timestamp. Require MKV, untouched best video/native audio, forced original-language PGS, available non-SDH English PGS and chapters; eac3to >=3.52 -normal (legacy 3.34 only stated exception), or DGDemux/MakeMKV plus eac3to -check -normal log. Include conversion logs; multichannel LPCM requires official DTS-HD MA conversion; preserve TrueHD and other codecs. FLAC alone is not a trump reason.")
        if upload.kind == DISC:
            return self.review("Complete discs may coexist for documented regional dub/sub differences; verify complete contents and BDInfo bitrate scans", why="Do not create a trump from region or filenames alone. Multi-disc releases require per-disc information where applicable.")
        if upload.kind in {ENCODE, WEBRIP}:
            relevant = [p for p in web if p.resolution != "720p" and not dead(p)]
            high_sdr = [p for p in web if p.resolution == "2160p" and p.is_sdr and not dead(p)]
            why = "Check encode lottery/offers/in-progress reservations. Primary audio depends on resolution, native language, channels and internal/external status; UHD follows remux rules. English dubs are allowed only for animation. Confirm forced subtitles and no forbidden re-encode."
            if competitors:
                why += " Replacement needs 4-6 source/new/old B-frame comparisons for scene/external encodes; old internals need 5-10 and confirmed fixes, noticeably better source or significant audio/video improvement and must be transparent with the source. Marginal changes/subtitles/commentary alone are not enough. Dead releases have the stated comparison exception."
            if relevant:
                why += " Internal encode/WEB coexistence needs 4-6 source/new/WEB B-frame comparisons unless the other release is dead or 720p WEB."
            if high_sdr:
                why += " Compare Blu-ray against the existing high-bitrate 4K SDR WEB before encoding; only the best source/version is allowed and lottery rules still apply."
            return self.review("Encoding rights, source choice, comparisons and audio/subtitle compliance require verification", [*competitors, *relevant], why=why)
        if upload.kind == WEBDL:
            if competitors:
                return self.review("An equivalent WEB-DL exists; verify a permitted quality/source replacement, not an assumed extra provider/HDR slot", competitors)
            if encodes:
                ma4k = upload.resolution == "2160p" and meta is not None and str(meta.service or "").upper() in {"MA", "MOVIES ANYWHERE", "MOVIESANYWHERE"}
                if not ma4k and upload.resolution != "720p" and any(not dead(p) for p in encodes):
                    return self.review("WEB-DL may coexist with an internal encode only with 4-6 source/new/old B-frame comparisons", why="Exceptions: the other release is dead, 720p WEB-DL, or Movies Anywhere 4K WEB-DL. Do not invent quality evidence or internal status.")
            if meta is not None and not meta.service:
                return self.review("Verify that this is restricted, untouched WEB-DL content, not a public download or encoded capture")
            return self.decision(Verdict.ALLOW, "No equivalent WEB-DL is listed; restricted, untouched WEB content may be uploaded",
                                 notes=["This does not verify provenance, subtitles/dubs, signup/lottery rights, or source quality. PNG screenshot failures retain the operator-requested warning-and-continue behavior."])
        return self.review("Verify eligibility and source/category-specific HDBits requirements before uploading", why="HDTV/VOD/feeds, IPTV, WEB-CAP, WMV HD/D-Theater/DVD-A, professional/amateur offers and special categories need their actual provenance/offer requirements checked. No automatic approval is implied.")

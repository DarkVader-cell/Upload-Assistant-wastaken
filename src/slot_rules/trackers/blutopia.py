# Upload Assistant © 2026 Audionut & wastaken7 — Licensed under UAPL v1.0
"""BLU coexistence recommendations from operator-supplied guidelines.

Metadata is not quality proof. No HDR-layer rank automatically establishes a
better stream, and untouched originals remain alongside derived hybrids.
"""

import re
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

from src.meta import Meta
from src.screenshot_manifest import files as manifest_files
from src.slot_rules.base import SlotRules, is_repack_of
from src.slot_rules.models import SlotDecision, Verdict
from src.slot_rules.profile import DISC, ENCODE, H264, H265, HDTV, REMUX, SD, WEBDL, WEBRIP, ReleaseProfile, _language_code, audio_family, channel_count

DERIVED_DV_ALERT = (
    "This release contains a Derived Dolby Vision layer. The WEB Dolby Vision layer was injected using dovi_tool. Mismatches between Blu-ray and WEB stream masters may occur."
)
CUTS = frozenset({"directors", "extended", "uncut", "unrated", "final_cut", "open_matte"})
REMINDERS = (
    "Verify original primary audio/allowed English dub, English subtitles (embedded or manager), flags/tags and source mixes/commentaries/scores; SHOULD is MUST for personal releases. Recommended improvements must retain every existing quality, including named chapters.",
    "Verify uniform original filenames, single-file/multiple-file layout, no extraneous payload files/PII/advertising/templates, English description. Seed ≥7 days OR 5 active seeders. If slow (<100Mbps) or unconnectable, wait 24h OR 2 seeders before another upload. Exceptions require helpdesk approval.",
    "REPACK/PROPER/RERip/RE-ISSUE replaces its verified original only. Dead-equivalent eligibility needs unanswered reseed ≥1 week plus last seed >1 month, OR last seed >2 months with equal/better quality; seed count alone proves neither.",
)


def screenshot_count(m):
    count = len(m.image_list or [])
    if count < 3 and m.uuid and m.base_dir:
        with suppress(OSError, ValueError):
            count = max(count, len(manifest_files(m.base_dir, m.uuid)))
    return count


def track_family(t):
    text = " ".join(str(t.get(k) or "") for k in ["Format", "Format_Commercial_IfAny", "Format_Commercial_Name", "Format_AdditionalFeatures", "Format_Profile"])
    if "mpeg audio" in text.casefold() and re.search(r"layer[ ._-]*(?:2|ii)\b", text, re.I):
        return "mp2"
    return audio_family(text)


class BlutopiaSlotRules(SlotRules):
    TRACKER = "BLUTOPIA"
    RULES_DATE = date(2026, 10, 20)

    def decision(self, verdict, reason, conflicts=(), notes=(), *, slot="", why="") -> SlotDecision:
        result = super().decision(verdict, reason, conflicts, [*notes, *REMINDERS], slot=slot, why=why)
        result.requires_evidence = verdict is Verdict.REVIEW
        return result

    def block(self, reason):
        result = self.decision(Verdict.BLOCK, reason)
        result.constraint_violation = True
        return result

    def _requirements(self, p):
        pending = []
        m = self.meta if isinstance(self.meta, Meta) else None
        prores_trailer = bool(m and m.get("BLUTOPIA_prores_trailer") is True)
        encoded = p.kind in {ENCODE, WEBRIP} and not prores_trailer
        if encoded and p.resolution not in {None, "OTHER", "720p", "1080p", "2160p"}:
            return "Encodes must be 720p, 1080p or 2160p", pending
        if encoded and p.codec is not None and p.codec not in {H264, H265}:
            return "BLU encodes must use x264/x265; general AV1 permission does not allow AV1 encodes", pending
        if not m:
            return None, pending
        get = m.get
        if m.personalrelease and get("BLUTOPIA_should_failures"):
            return "SHOULD requirements are MUST for personal releases; declared applicable failures must be fixed", pending
        if encoded and re.search(r"vp[ ._-]?9|prores|cineform|jpeg[ ._-]?2000", str(m.video_codec or "") + " " + str(m.video_encode or ""), re.I):
            return "BLU encodes must use x264/x265, not another generally permitted source codec", pending
        if prores_trailer:
            if p.codec is not None:
                return "Declared ProRes trailer exception conflicts with a known non-ProRes video codec", pending
            pending.append(
                "Verify official ProRes trailer eligibility and actual ProRes video/source; this content exception is not an automatic encode/container/type permission"
            )
        if m.category in {"AUDIO", "MUSIC", "BOOK", "APP", "GAME", "XXX", "SPORTS"}:
            return "This category is prohibited/not a BLU movie, TV or FanRes video category", pending
        if any(
            get(k) is True
            for k in [
                "sportscast",
                "music_video",
                "pornographic",
                "bootleg",
                "pre_retail_content",
                "personally_identifying_content",
                "BLUTOPIA_invalid_hybrid",
                "BLUTOPIA_banned_group",
            ]
        ):
            return "Declared prohibited content, PII, banned-group release or invalid hybrid", pending
        if str(m.service or "").casefold() in {"yt", "youtube", "dailymotion"} or get("social_media_source") is True:
            return "Social-media video platform content is prohibited on BLU", pending
        if str(m.source or "").upper() in {"CAM", "TS", "TELESYNC", "BOOTLEG", "PRE-RETAIL"}:
            return "Bootleg/pre-retail sources are prohibited", pending
        if str(m.source or "").upper() in {"TC", "TELECINE", "R5", "SCREENER", "DVDSCR", "DCP", "WORKPRINT", "WP"}:
            pending.append(
                "Verify actual source release/authenticity and applicable retail/FanRes requirements; this source label alone does not establish prohibited pre-retail content"
            )
        if any(get(k) for k in ["BLUTOPIA_extraneous_files", "BLUTOPIA_torrent_has_single_file_folder", "BLUTOPIA_multiple_top_level_directories"]):
            return "Torrent file layout/extraneous files violate BLU packaging requirements", pending
        tools = get("BLUTOPIA_tools_used", get("tools_used", []))
        tools = [tools] if isinstance(tools, str) else tools
        if isinstance(tools, (list, tuple, set)) and any(Path(str(t).replace("\\", "/")).stem.casefold() in {"hdr10plus_tool", "truehdd"} for t in tools):
            return "hdr10plus_tool and truehdd are prohibited; installed binaries or title words alone are not usage evidence", pending
        if get("BLUTOPIA_hdr10plus_injected_with_hdr10plus_tool") is True:
            return "Second-source HDR10+ injected with hdr10plus_tool is prohibited; only official-tool injections are allowed", pending
        tracks = (m.mediainfo or {}).get("media", {}).get("track", [])
        tracks = tracks if isinstance(tracks, list) else []
        audio = [t for t in tracks if isinstance(t, dict) and t.get("@type") == "Audio"]
        genres = {str(g).casefold() for g in (m.genres or [])}
        anime = m.anime
        animated = anime or "animation" in genres
        live = get("BLUTOPIA_live_action") is True or (bool(genres) and not animated)
        if encoded and p.is_sdr and p.codec == H265 and live:
            return "SDR live-action encodes must use x264, not x265", pending
        if encoded and p.hi10p and not anime:
            if live or m.not_anime:
                return "Hi10P is prohibited outside the anime exception", pending
            pending.append("Hi10P is only permitted by the anime exception; verify anime status or use x265 where allowed")
        iso = m.container.lower() == "iso" or Path(m.path or "").suffix.lower() == ".iso"
        if p.kind == DISC:
            if iso and (not p.is_3d or str(m.is_disc or "").upper() in {"DVD", "HDDVD", "HDDVD_TS"}):
                return "Only MVC 3D Blu-ray may use ISO; other discs require BDMV/HDDVD_TS/VIDEO_TS folders", pending
            if get("BLUTOPIA_custom_disc") is True:
                return "Custom/DIY discs are prohibited", pending
            if p.is_3d and not iso:
                if get("BLUTOPIA_mvc") is True or "MVC" in str(m.video_codec or "").upper():
                    return "MVC 3D Blu-ray discs must use ISO", pending
                pending.append("Verify MVC 3D Blu-ray is in ISO, not extracted folders")
            if not iso and screenshot_count(m) < 3:
                pending.append("At least three valid screenshots are required outside the Blu-ray ISO exception")
            if (get("BLUTOPIA_movie_collection") is True or get("BLUTOPIA_multi_season") is True) and get("BLUTOPIA_official_retail_boxset") is False:
                return "Movie collections/multiple seasons must be direct official retail disc box sets", pending
            pending.append("Verify unique retail unmodified disc/box-set contents and required BD Quick Summary, DVD IFO+largest VOB, or HD-DVD main EVO reports")
            return None, pending
        container = m.container.casefold() or Path(m.path or "").suffix.lower().lstrip(".")
        if prores_trailer:
            pending.append("Verify the appropriate native ProRes trailer container/type and all non-disc audio/description requirements")
        if not prores_trailer and p.kind in {REMUX, ENCODE, WEBRIP, WEBDL, HDTV} and container not in {"mkv", "matroska"}:
            video_hdr = " ".join(
                str(t.get(k) or "") for t in tracks if isinstance(t, dict) and t.get("@type") == "Video" for k in ["HDR_Format", "HDR_Format_Profile", "HDR_Format_String"]
            )
            profiles = set(re.findall(r"dv(?:he|h1)\.0?([1-9])\b|profile[ .:_-]*([1-9])\b", video_hdr, re.I))
            profiles = {a or b for a, b in profiles}
            dv5 = profiles == {"5"}
            if (p.kind == HDTV and container in {"ts", "mpeg-ts"}) or (p.kind in {WEBDL, HDTV} and container in {"mp4", "mpeg-4"} and dv5):
                pass
            elif not container or (not profiles and p.kind in {WEBDL, HDTV} and container in {"mp4", "mpeg-4"} and p.hdr and "DV" in p.hdr):
                pending.append("Verify MKV or the confirmed DV Profile 5 MP4 / HDTV TS exception; bare DV is not Profile 5 proof")
            else:
                return "This non-disc format requires MKV outside confirmed DV Profile 5 MP4 / HDTV TS exceptions", pending
        families = [track_family(t) for t in audio]
        for t, f in zip(audio, families, strict=True):
            channels = channel_count(str(t.get("Channels") or ""))
            supplementary = bool(re.search(r"commentary|isolated.?score|interview", str(t.get("Title") or ""), re.I))
            if f == "flac" and channels and channels > 2 and not (encoded and anime and channels == 6):
                return "Multichannel FLAC is prohibited except the anime encode FLAC 5.1 exception", pending
            if f == "aac" and channels and channels > 2:
                if encoded or get("BLUTOPIA_audio_untouched") is False:
                    return "Multichannel AAC is prohibited in encodes; other formats need untouched-audio proof", pending
                pending.append("Verify the untouched multichannel AAC exception")
            raw = str(t.get("Format") or "").casefold()
            if "opus" in raw or "vorbis" in raw or raw == "ogg":
                return "Opus/OGG/Vorbis are not allowed by the supplied BLU audio rules", pending
            if f == "mp3" and not supplementary:
                return "MP3 is only allowed for qualifying supplementary tracks, not main audio", pending
            if f == "mp3" and supplementary:
                pending.append("Supplementary MP3 requires proof no original-form or other suitable-codec version is available")
            if f == "mp2":
                pending.append("MP2 requires untouched HDTV/DVD provenance")
        truehd = sum(f == "truehd" for f in families)
        ac3 = [t for t, f in zip(audio, families, strict=True) if f == "dd"]
        if truehd:
            if len(ac3) < truehd:
                return "Every TrueHD track needs a standalone AC-3 compatibility track; WEB DD+ is not the BLU substitute", pending
            for t in ac3:
                extra = t.get("extra") or {}
                bsid = t.get("bsid") or t.get("Bsid") or (extra.get("bsid") if isinstance(extra, dict) else None)
                if bsid is not None and str(bsid) != "6":
                    return "TrueHD compatibility AC-3 must be industry-standard bsid=6", pending
                if bsid is None:
                    pending.append("Verify compatibility AC-3 bsid=6 using Advanced MediaInfo")
            pending.append("Verify exactly one compatibility track per mix; do not include embedded cores separately from extensions")
        if encoded:
            for track in tracks:
                if not isinstance(track, dict) or track.get("@type") != "Video":
                    continue
                library = " ".join(str(track.get(k) or "") for k in ["Encoded_Library", "Encoded_Library_Name", "Encoded_Library_String"])
                if re.search(r"\bnvenc\b|\bqsv\b|\bintel.*quick.?sync\b|\bateme\b", library, re.I):
                    return "Encodes require x264/x265, not a known hardware/other encoder", pending
                # ABR alone does not establish one-pass: x265 may expose
                # stats-read rather than pass. Lossless CRF can also show CQP.
                # Rate-control provenance stays in the required encode review.
            if get("BLUTOPIA_uncropped_bars") is True or get("BLUTOPIA_invalid_encode_mode") is True:
                return "Encodes require reasonably cropped bars and CRF/multi-pass VBR", pending
            if get("BLUTOPIA_missing_encode_settings") is True:
                return "x264/x265 metadata must be present in MediaInfo", pending
            primary = _language_code(m.original_language)
            native = [
                t
                for t in audio
                if not re.search(r"commentary|compat|isolated.?score", str(t.get("Title") or ""), re.I) and (not primary or _language_code(t.get("Language")) == primary)
            ]
            if p.resolution == "2160p" and p.codec == H265:
                families_native = {track_family(t) for t in native}
                if families_native and families_native <= {"dd", "dd+", "dts", "aac", "mp3", "mp2"}:
                    return "2160p x265 main audio must be lossless", pending
                if not families_native:
                    pending.append("Verify lossless primary/native main audio for 2160p x265; playback-default dub/compatibility is not main-audio identity")
            pending.append(
                "Verify high-standard untouched-source encode with source/encode comparisons, x264/x265 metadata, CRF/multipass, crop and bitrate. 1080p Quality/Compromise audio tiers, official encoders, bit-depth/dither, commentary and compatibility bitrates require actual evidence; size is not transparency"
            )
            if not animated and not live:
                pending.append("Confirm animation/anime versus live-action; SDR live-action must use x264")
        if p.hybrid:
            pending.append(
                "Validate matching masters, colour/brightness, aspect ratio throughout and identical intro/outro; verify permitted tools and HDR-layer provenance. HDR10+ second-source injection requires official tools, never hdr10plus_tool"
            )
        if p.kind == WEBDL and p.hdr and "DV" in p.hdr and ("HDR10" in p.hdr or "HDR10+" in p.hdr):
            pending.append("Verify native versus derived DV/HDR stream provenance; extra metadata alone does not establish superior quality")
        derived = get("BLUTOPIA_derived_dv") is True or m.webdv is True
        if derived and p.kind in {REMUX, ENCODE, WEBRIP}:
            fanres = (m.category == "MOVIE" and "FANRES" in m.edition) or m.category == "FANRES" or (m.tracker_status.get("BLUTOPIA") or {}).get("other") is True
            if not fanres:
                return "Derived WEB P5/P8 DV remuxes/encodes must use FANRES", pending
            if not (m.description or "").startswith(DERIVED_DV_ALERT):
                pending.append("Prepend the exact left-aligned derived-DV alert above the unchanged original description: " + DERIVED_DV_ALERT)
            pending.append(
                "Provide HDR BD vs HDR WEB and HDR BD vs DV WEB converted to PQ grades, both-source DV brightness plots, DV source, Metafier log and dovi_tool summary"
            )
        if derived and p.kind == WEBDL:
            if "hybrid" in m.name.casefold():
                return "Derived-DV WEB-DL must not use HYBRID in its title; source notes are SHOULD, no derived alert is required", pending
            pending.append("Verify valid matched masters/aspect/intro/outro and actual HDR/raw-stream quality; metadata alone gives no priority")
        if m.category == "TV" and not m.tv_pack and get("season_completed") is True:
            pilot = re.sub(r"\D", "", m.season or "") == "01" and re.sub(r"\D", "", m.episode or "") == "01"
            if not pilot:
                try:
                    released = datetime.fromisoformat(str(get("BLUTOPIA_source_released_at") or "").replace("Z", "+00:00"))
                    if released.tzinfo is None:
                        raise ValueError("timezone required")
                    age = (datetime.now(UTC) - released).total_seconds()
                    if age < 0:
                        pending.append("Source-release timestamp is in the future; verify actual release eligibility and clock")
                    if age > 72 * 3600:
                        return "Completed-season individual episodes are outside the 72-hour source-release grace period; use a season pack", pending
                except ValueError, TypeError:
                    pending.append("Verify the 72-hour window from the actual source release, not episode airdate; S01E01 pilots are exempt")
        if get("BLUTOPIA_concert") is True:
            web = p.kind in {WEBDL, WEBRIP} or str(m.source or "").casefold() == "web"
            if web:
                if not get("BLUTOPIA_modq_effective", m.modq):
                    return "WEB concerts require staff approval and moderation queue", pending
                pending.append("Verify prior forum staff approval for WEB concert")
            pending.append(
                "Concert MKVs require a named tracklist; verify best lossless surround plus stereo/mono assets (DTS-HD MA mono), and documentary versus concert classification"
            )
        if get("BLUTOPIA_movie_collection") is True or get("BLUTOPIA_multi_season") is True:
            return "Movie collections/multi-season uploads must be direct official retail disc box sets", pending
        if get("upscaled") is True:
            pending.append("Non-disc SD upscales require prior helpdesk/staff approval")
        if get("BLUTOPIA_extras") is True:
            pending.append(
                "Extras must be separate, streaming/disc sourced and source-faithful, descriptively named under Behind The Scenes, Deleted Scenes, Featurettes, Interviews, Scenes, Shorts, Trailers or Other; encoding requires higher-quality proof"
            )
        if m.personalrelease:
            pending.append("Personal release: SHOULD requirements are MUST, including applicable sources, audio assets, tags, logs and subtitle hygiene")
        if screenshot_count(m) < 3:
            pending.append("Verify at least three valid screenshots and required report/parser fields in the actual description")
        if not m.mediainfo:
            pending.append("Supply required MediaInfo in the parser; missing reports are not a valid upload")
        if not p.audio_languages or not m.original_language:
            pending.append("Verify original primary audio language and allowed dub/supplementary roles; missing language metadata is not conformity proof")
        elif str(m.original_language).casefold() not in {"en", "eng", "english"} and "en" not in (p.subtitle_languages or set()):
            pending.append("Non-English content must provide English subtitles, embedded or via the subtitle manager")
        return None, pending

    def evaluate(self, upload: ReleaseProfile, existing: Sequence[ReleaseProfile]):
        from src.trackers.UNIT3D.blutopia import Blutopia

        def normalize(p):
            flags = p.entry.get("flags") or []
            flags = flags if isinstance(flags, (list, tuple, set)) else []
            hybrid = p.hybrid or p.entry.get("hybrid") is True or p.entry.get("derived_dv") is True or any(str(f).casefold() == "hybrid" for f in flags)
            return replace(p, hybrid=hybrid, repack=max(p.repack, 1 if re.search(r"\bre[ ._-]?issue\b", p.name, re.I) else 0))

        upload = normalize(upload)
        existing = [normalize(p) for p in existing]
        if isinstance(self.meta, Meta) and (self.meta.webdv or self.meta.get("BLUTOPIA_derived_dv") is True):
            upload = replace(upload, hybrid=True)
        if (upload.group or "").casefold() in {g.lstrip("-").casefold() for g in Blutopia.banned_groups}:
            return self.block("This release group is banned on BLU")
        violation, pending = self._requirements(upload)
        if violation:
            return self.block(violation)
        exact = [p for p in existing if p.exact]
        if exact:
            return self.decision(Verdict.BLOCK, "This exact release is already on BLU", exact)
        if isinstance(self.meta, Meta) and self.meta.get("BLUTOPIA_prores_trailer") is True:
            return self.decision(Verdict.REVIEW, "Verify the ProRes trailer content exception and correct format classification", why=" ".join(pending))
        if upload.kind is None or upload.resolution in {None, "OTHER"}:
            return self.decision(Verdict.REVIEW, "Unknown BLU format/resolution; verify eligibility and slot before uploading", why=" ".join(pending))
        if upload.resolution == SD and upload.kind in {REMUX, WEBDL}:
            pending.append("SD DVD remux/WEB-DL needs no non-upscaled HD version, never-HD OAR or important unique assets; absence from this search is not proof")
        if isinstance(self.meta, Meta) and self.meta.category == "TV":
            pending.append(
                "Complete same-source/same-quality seasons replace individual episodes/incomplete packs; WEB season packs replace HDTV unless inferior; individual seasons of the same source/resolution replace COMPLETE series packs. Verify source, quality and completeness rather than title markers alone"
            )
        same = [p for p in existing if p.resolution == upload.resolution and (p.edition & CUTS) == (upload.edition & CUTS) and p.is_3d == upload.is_3d]
        if upload.kind == DISC:
            return self.decision(
                Verdict.REVIEW,
                "Unique retail discs coexist, including valid retail box sets and their individual discs; verify uniqueness/reports/packaging",
                why=" ".join(pending),
            )
        encoded = upload.kind in {ENCODE, WEBRIP}
        if encoded:
            holders = [p for p in same if p.kind in {ENCODE, WEBRIP}]
            web = [
                p
                for p in existing
                if p.kind == WEBDL and (p.edition & CUTS) == (upload.edition & CUTS) and (not p.provider or not upload.provider or p.provider == upload.provider)
            ]
            if web:
                pending.append("WEBRip cannot coexist with its source WEB-DL without comparisons proving significant visual improvement")
            limit = 2 if upload.resolution == "1080p" else 1
            return self.decision(
                Verdict.REVIEW,
                f"Encodes require meaningful benefits/comparisons; ordinary limits are 1x720p, 2x1080p, 1x2160p ({len(holders)}/{limit} listed here)",
                holders,
                why=" ".join(pending),
            )
        if upload.kind == WEBDL and any(v is None for v in [upload.provider, upload.codec, upload.hdr]):
            pending.append("Confirm provider, video codec and colour space; missing traits do not prove a vacant provider slot")
        holders = [p for p in same if p.kind == upload.kind]
        if upload.kind == WEBDL:
            holders = [
                p
                for p in holders
                if (not p.provider or not upload.provider or p.provider == upload.provider)
                and (not p.codec or not upload.codec or p.codec == upload.codec)
                and (p.hdr is None or upload.hdr is None or p.is_sdr == upload.is_sdr)
            ]
            native = [p for p in holders if p.hybrid != upload.hybrid]
            if native:
                pending.append("Untouched original HDR and a valid derived hybrid coexist; do not report the original merely for lacking metadata")
                holders = [p for p in holders if p not in native]
        if upload.kind == WEBDL:
            rips = [p for p in same if p.kind == WEBRIP and (not p.provider or not upload.provider or p.provider == upload.provider)]
            if rips:
                pending.append("WEB-DL trumps WEBRip of the same source/source resolution; verify source identity and any significant-improvement coexistence case")
        if upload.kind == REMUX:
            pending.append(
                "Verify source/master and audio/asset completeness. P7 MEL cannot trump Blu-ray-sourced P8.1; FEL beats MEL only with same/better HDR10 base. Disc HDR10+/DV is SHOULD; profiles/source/grade/master differences require evidence, never numeric ranking"
            )
        if holders:
            replacement = all(is_repack_of(upload, p) for p in holders)
            reason = (
                "Confirmed same-release REPACK/PROPER/RERip/RE-ISSUE; verify retained assets and fixes"
                if replacement
                else "Potential same-slot competition: justify superior quality/assets or a documented different-master coexistence"
            )
            return self.decision(Verdict.REVIEW, reason, holders, why=" ".join(pending))
        unknown = [
            p for p in existing if p.kind in {None, upload.kind} and p.resolution in {None, "OTHER", upload.resolution} and (p.kind is None or p.resolution in {None, "OTHER"})
        ]
        if unknown:
            return self.decision(Verdict.REVIEW, "Potential BLU slot occupants have unknown traits; verify before assuming vacancy", unknown, why=" ".join(pending))
        if pending:
            return self.decision(Verdict.REVIEW, "Verify required BLU eligibility/source/quality/description evidence", why=" ".join(pending))
        return self.decision(
            Verdict.ALLOW,
            "No competing listed release occupies this provider/format/cut/resolution combination",
            notes=["Verify source authenticity, seeding commitments and actual upload requirements; metadata is not certification."],
        )

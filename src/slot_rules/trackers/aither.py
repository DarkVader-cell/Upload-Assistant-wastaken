# Upload Assistant © 2026 Audionut & wastaken7 — Licensed under UAPL v1.0
"""Aither recommendations from the operator-supplied 2026-10-19 guidelines."""

import re
from collections.abc import Sequence
from dataclasses import replace
from datetime import date

from src.meta import Meta
from src.slot_rules.base import SlotKey, SlotRules, UnknownTraitError, is_repack_of, size_diff_ratio, slot_label
from src.slot_rules.models import SlotDecision, Verdict
from src.slot_rules.profile import DISC, DV, DVDRIP, ENCODE, H264, H265, HDR10, HDR10P, REMUX, SD, WEBDL, WEBRIP, ReleaseProfile

UNLISTED = "unlisted"
CUTS = frozenset({"directors", "extended", "uncut", "unrated", "final_cut"})
ACCESSIBILITY = frozenset({"ASL", "BSL", "BASL", "AD", "AUDIO DESCRIPTION", "AUDIO DESCRIPTIONS"})


class AitherSlotRules(SlotRules):
    TRACKER = "AITHER"
    RULES_DATE = date(2026, 10, 19)

    @staticmethod
    def _policy(p: ReleaseProfile) -> str:
        if p.kind == DISC:
            return 'Unlimited unique full-disc slots; verify permitted retail format/content/regions.'
        if p.resolution == SD:
            return 'One SD WEB-DL, one SD DVDRip and one SD DVD Remux slot; only if no equivalent HD retail media source is available.'
        if p.kind == WEBDL:
            if p.resolution == '720p':
                return 'One 720p H.264 WEB slot.'
            if p.resolution in {'1080p','1440p'}:
                prefix='1440p requires no available 2160p source. ' if p.resolution=='1440p' else ''
                return prefix+'One H.264 WEB, one DV-only H.265 WEB, and one HDR or DV/HDR H.265 WEB slot. DV/HDR trumps HDR in the last slot.'
            if p.resolution == '2160p':
                return 'Four H.265 WEB slots: SDR; DV-only; HDR or DV/HDR (DV/HDR trumps HDR); HDR10+ or DV/HDR10+ (DV/HDR10+ trumps HDR10+). Providers do not create extra Aither slots.'
        if p.kind in {ENCODE,WEBRIP}:
            if p.resolution == '720p':
                return 'One 720p H.264 encode slot.'
            if p.resolution == '1080p' and p.codec == H264:
                return 'Two x264 slots: Quality (transparent) and Retention (space-saving). Less than 20% size difference competes; a larger gap alone does not prove a valid alternative. WEB downscales/animation require comparisons.'
            if p.resolution == '1080p':
                return 'One ordinary x265 slot; one retail HDR/DV-HDR x265 slot (DV/HDR trumps HDR); one hybrid HDR10+/DV-HDR10+ x265 slot (DV/HDR10+ trumps HDR10+ and DV/HDR). Hybrid grading evidence is required.'
            if p.resolution == '2160p':
                return 'One SDR x265, one retail HDR/DV-HDR x265 (DV/HDR trumps HDR), one hybrid HDR10+/DV-HDR/DV-HDR10+ x265 (DV/HDR10+ trumps DV/HDR and HDR10+). Disc DV normally beats hybrid; grade checks/plots are required.'
        if p.kind == REMUX:
            if p.resolution == '1080p':
                return 'One 1080p Remux slot.'
            if p.resolution == '2160p':
                return 'One SDR, one retail HDR/DV-HDR (DV/HDR trumps HDR), one hybrid HDR10+/DV-HDR/DV-HDR10+ Remux (DV/HDR10+ trumps DV/HDR and HDR10+). Disc DV normally beats hybrid unless proven inferior; grade checks/plots required.'
        return 'Verify a listed Aither format/resolution slot and any required source/comparison/staff evidence.'

    def decision(self, verdict: Verdict, reason: str, conflicts: Sequence[ReleaseProfile] = (), notes: Sequence[str] = (), *, slot: str = "", why: str = "") -> SlotDecision:
        candidate = getattr(self, '_candidate', None)
        details = list(notes)
        if candidate is not None:
            details.extend([f'Detected incoming: {candidate.resolution or "unknown resolution"} · {candidate.kind or "unknown type"} · {candidate.codec or "unknown codec"} · {candidate.hdr_label}.',
                            'Aither rule: '+self._policy(candidate)])
        result = super().decision(verdict, reason, conflicts, details, slot=slot, why=why)
        result.requires_evidence = verdict is Verdict.REVIEW
        return result

    def review(self, reason: str, conflicts: Sequence[ReleaseProfile] = (), *, slot: str = "", why: str = "") -> SlotDecision:
        return self.decision(Verdict.REVIEW, reason, conflicts, slot=slot, why=why)

    @staticmethod
    def _hybrid(profile: ReleaseProfile) -> bool:
        flags = profile.entry.get("flags") or []
        flags = flags if isinstance(flags, (list, tuple, set)) else []
        return profile.hybrid or profile.entry.get("hybrid") is True or any(str(flag).casefold() == "hybrid" for flag in flags)

    def evaluate(self, upload: ReleaseProfile, existing: Sequence[ReleaseProfile]) -> SlotDecision | None:
        declared_hybrid = isinstance(self.meta, Meta) and (self.meta.get("AITHER_hybrid") is True or self.meta.webdv)
        upload = replace(upload, hybrid=self._hybrid(upload) or declared_hybrid)
        existing = [replace(p, hybrid=self._hybrid(p)) for p in existing]
        self._candidate = upload
        self._title_releases = existing
        if upload.kind == DISC:
            exact = [p for p in existing if p.exact]
            if exact:
                return self.decision(Verdict.BLOCK, "This exact full disc is already on Aither", exact)
            access = self._accessibility(upload)
            if access and not upload.internal:
                return self.decision(Verdict.BLOCK, "Additional accessibility slots are only available to Aither internals")
            if "open_matte" in upload.edition or any("open_matte" in p.edition and p.kind == DISC and p.resolution == upload.resolution for p in existing):
                return self.review("Open Matte/OAR separate slots require staff approval before uploading")
            if access:
                return self.review("Verify internal eligibility and accessibility features")
            if isinstance(self.meta, Meta) and self.meta.extras:
                return self.review("Verify the content and packaging of the additional disc-extras slot")
            discs = [p for p in existing if p.kind == DISC and p.resolution == upload.resolution and p.is_3d == upload.is_3d]
            label = str(self.meta.disctype or "") if isinstance(self.meta, Meta) else ""
            label += " " + upload.name
            if not re.search(r"\b(?:DVD[ ._-]?[59]|BD[ ._-]?(?:50|100))\b", label, re.I):
                return self.review("Confirm a supported DVD5/DVD9/BD50/BD100 format or obtain an exception")
            if discs:
                return self.review("Full-disc slots are unlimited only for different content or regions; document the differences")
            return self.decision(Verdict.ALLOW, "No equivalent full disc is listed; DVD5/DVD9/BD50/BD100 have unlimited content/region slots",
                                 notes=["Verify the disc format, actual contents and region; size alone does not establish them."])
        return super().evaluate(upload, existing)

    @staticmethod
    def _edition(profile: ReleaseProfile) -> frozenset[str]:
        return profile.edition & (CUTS | {"open_matte"})

    def _retail(self, profile: ReleaseProfile) -> bool:
        text = str(profile.entry.get("Source") or profile.entry.get("source") or "") + " " + profile.name
        if profile is getattr(self, "_candidate", None) and isinstance(self.meta, Meta):
            text += " " + str(self.meta.source or "")
        declared = str(profile.entry.get("Source") or profile.entry.get("source") or "").casefold() == "retail"
        return (declared or bool(re.search(r"blu[ ._-]?ray|hd[ ._-]?dvd|\bdvd\b", text, re.I))) and not profile.hybrid

    def web_range(self, profile: ReleaseProfile, *, split_hdr10p: bool) -> str:
        hdr = self.require(profile.hdr, "dynamic range")
        if not hdr:
            return "SDR"
        if hdr == {DV}:
            return "DV"
        if not hdr & {HDR10, HDR10P}:
            raise UnknownTraitError("HDR10 compatibility is not established")
        return "HDR10+" if split_hdr10p and HDR10P in hdr else "HDR"

    def disc_range(self, profile: ReleaseProfile, *, sdr_slot: bool) -> str:
        hdr = self.require(profile.hdr, "dynamic range")
        if not hdr:
            return "SDR" if sdr_slot else UNLISTED
        if not hdr & {HDR10, HDR10P}:
            return UNLISTED
        if profile.hybrid:
            if profile.resolution == "1080p" and HDR10P not in hdr:
                return UNLISTED
            if HDR10P not in hdr and DV not in hdr:
                return UNLISTED
            return "HYBRID"
        if not self._retail(profile):
            raise UnknownTraitError("Retail source is not established; HDR10+ alone does not identify a hybrid")
        return "HDR"

    def key(self, profile: ReleaseProfile) -> SlotKey:
        res = self.require(profile.resolution, "resolution")
        kind = self.require(profile.kind, "release type")
        edition = (self._edition(profile), profile.is_3d)
        if res == SD:
            mapping = {WEBDL: "WEB-DL", DVDRIP: "DVDRip", ENCODE: "DVDRip", REMUX: "DVD Remux"}
            return (res, mapping.get(kind, UNLISTED), edition)
        if kind == REMUX:
            if res == "1080p":
                return (res, "Remux", edition)
            if res == "2160p":
                return (res, "Remux", self.disc_range(profile, sdr_slot=True), edition)
            return (res, UNLISTED, kind)
        codec = self.require(profile.codec, "video codec")
        if kind == WEBDL:
            if res == "720p":
                return (res, "WEB", edition) if codec == H264 else (res, UNLISTED, kind)
            if res in {"1080p", "1440p"}:
                if codec == H264 and not self.require(profile.hdr, "dynamic range"):
                    return (res, "WEB", "H.264", edition)
                dynamic = self.web_range(profile, split_hdr10p=False)
                return (res, "WEB", dynamic, edition) if codec == H265 and dynamic != "SDR" else (res, UNLISTED, kind)
            if res == "2160p":
                return (res, "WEB", self.web_range(profile, split_hdr10p=True), edition) if codec == H265 else (res, UNLISTED, kind)
        if kind in {ENCODE, WEBRIP}:
            if res == "720p":
                return (res, "encode", edition) if codec == H264 else (res, UNLISTED, kind)
            if res == "1080p":
                if codec == H264:
                    return (res, "x264 encode", edition)
                if codec == H265:
                    return (res, "x265 encode", self.disc_range(profile, sdr_slot=True), edition)
            if res == "2160p" and codec == H265:
                return (res, "x265 encode", self.disc_range(profile, sdr_slot=True), edition)
        return (res, UNLISTED, kind)

    def _family(self, upload: ReleaseProfile, existing: ReleaseProfile) -> bool:
        if upload.is_3d != existing.is_3d or self._edition(upload) != self._edition(existing):
            return False
        if existing.resolution not in {None, "OTHER", upload.resolution}:
            return False
        equivalent_kind = {ENCODE, WEBRIP, DVDRIP} if upload.kind in {ENCODE, WEBRIP, DVDRIP} else {upload.kind}
        if existing.kind is not None and existing.kind not in equivalent_kind:
            return False
        if upload.kind != REMUX and upload.resolution != SD and upload.codec and existing.codec and upload.codec != existing.codec:
            return False
        range_partition = (upload.kind == WEBDL and upload.resolution in {"1080p", "1440p", "2160p"}) or (
            upload.kind == ENCODE and (upload.resolution == "2160p" or (upload.resolution == "1080p" and upload.codec == H265))) or (
            upload.kind == REMUX and upload.resolution == "2160p")
        return not (range_partition and upload.hdr is not None and existing.hdr is not None and bool(upload.hdr) != bool(existing.hdr))

    def _accessibility(self, profile: ReleaseProfile) -> set[str]:
        values = profile.entry.get("accessibility") or profile.entry.get("flags") or []
        if profile is getattr(self, "_candidate", None) and isinstance(self.meta, Meta):
            values = self.meta.get("AITHER_accessibility", values)
        if isinstance(values, str):
            values = [values]
        return {str(value).upper() for value in values if str(value).upper() in ACCESSIBILITY} if isinstance(values, (list, tuple, set)) else set()

    def _trump(self, upload: ReleaseProfile, existing: ReleaseProfile) -> tuple[Verdict, str]:
        if is_repack_of(upload, existing):
            return Verdict.ALLOW, "A confirmed newer REPACK/PROPER replaces the same release."
        new, old = upload.hdr or frozenset(), existing.hdr or frozenset()
        if DV in new and HDR10P in new and HDR10P in old and DV not in old:
            return Verdict.ALLOW, "DV/HDR10+ takes precedence over HDR10+ in this slot."
        if upload.hybrid and DV in new and HDR10P in new and DV in old and HDR10 in old:
            return Verdict.ALLOW, "DV/HDR10+ takes precedence over DV/HDR in the hybrid slot, subject to grading evidence."
        if DV in new and HDR10P not in new and HDR10P in old:
            return Verdict.REVIEW, "The proposed replacement loses HDR10+; verify quality and an applicable trump exception."
        if DV in new and new & {HDR10, HDR10P} and old & {HDR10, HDR10P} and DV not in old:
            return Verdict.ALLOW, "DV/HDR takes precedence over HDR in this slot."
        detected = f'Detected incoming: {upload.hdr_label}; existing: {existing.hdr_label}. '
        if DV in old and DV not in new:
            return Verdict.BLOCK, detected+'The existing release already has Dolby Vision; an HDR-only upload is not the DV/HDR upgrade required by this rule.'
        if new == old:
            return Verdict.BLOCK, detected+'Both have the same detected dynamic range, so the DV/HDR-over-HDR or DV/HDR10+-over-HDR10+ preference adds no upgrade. Size/internal status alone does not justify replacing this occupant.'
        return Verdict.BLOCK, detected+'No applicable automatic Aither replacement condition is met. Check the slot rule and verified release traits, not internal status or size alone.'

    def decide(self, upload: ReleaseProfile, existing: Sequence[ReleaseProfile]) -> SlotDecision | None:
        family = [p for p in existing if self._family(upload, p)]
        title = getattr(self, "_title_releases", existing)
        accessibility = self._accessibility(upload)
        if accessibility:
            if not upload.internal:
                return self.decision(Verdict.BLOCK, "Additional accessibility slots are only available to Aither internals")
            return self.review("Verify the declared ASL/BSL/BASL/AD features and internal eligibility before using an accessibility slot")
        counterpart = any("open_matte" in p.edition and p.kind == upload.kind and p.resolution == upload.resolution
                          and (p.edition & CUTS) == (upload.edition & CUTS) for p in title)
        if "open_matte" in upload.edition or counterpart:
            return self.review("Open Matte/OAR separate slots require staff approval before uploading")
        if isinstance(self.meta, Meta) and self.meta.extras:
            return self.review("Disc extras may have additional slots; verify packaging and the need for the extra slot")
        web_encode = upload.kind in {ENCODE, WEBRIP} and bool(re.search(r"web[ ._-]?rip", upload.name, re.I))
        if upload.kind == ENCODE and isinstance(self.meta, Meta):
            web_encode = web_encode or str(self.meta.source or "").lower() in {"web", "webrip", "web-dl"}
        if upload.kind == WEBRIP or web_encode:
            return self.review("WEBRips require source/quality evidence and 10 comparison screenshots", family,
                               why="Use a higher-resolution WEB-DL, prove superiority, or confirm no WEB-DL exists. WEB-DL takes precedence. 1080p downscales from 2160p WEB must prove superiority to Blu-ray and use Encode/x264 slots; animation exceptions also need comparisons.")
        key = self.key(upload)
        label = slot_label(key) + (" · 3D" if upload.is_3d else "")
        if UNLISTED in key:
            return self.review("Aither has no listed slot for this format; staff may grant an additional slot with justification", slot=label)
        same_cut = [p for p in title if self._edition(p) == self._edition(upload) and p.is_3d == upload.is_3d]
        if upload.resolution == SD:
            hd = [p for p in same_cut if p.resolution in {"720p", "1080p", "1440p", "2160p"} and (p.kind in {DISC, WEBDL} or self._retail(p))]
            if hd:
                return self.decision(Verdict.BLOCK, "An equivalent HD retail source exists; SD WEB/DVDRip/DVD Remux is not allowed")
            return self.review("Confirm that no equivalent HD retail media source exists before using an SD slot", family, slot=label)
        if upload.resolution == "1440p":
            uhd = [p for p in same_cut if p.resolution == "2160p"]
            if uhd:
                return self.decision(Verdict.BLOCK, "A 2160p source is available; the 1440p slot cannot be used")
            return self.review("Confirm that no 2160p source is available before using a 1440p slot", family, slot=label)
        other_cuts = [p for p in title if p.kind == upload.kind and p.resolution == upload.resolution
                      and (p.edition & CUTS) != (upload.edition & CUTS)]
        if other_cuts or (upload.edition & {"imax", "ultimate", "special"}):
            return self.review("Alternate cuts may coexist only when actual content differences are documented; marketing labels alone are not new slots", slot=label)
        occupants = []
        for profile in family:
            try:
                if self.key(profile) == key:
                    occupants.append(profile)
            except UnknownTraitError:
                pass  # by_slot retains these as relevant unknowns.
        if upload.hybrid:
            priority = [p for p in family if not p.hybrid and DV in (p.hdr or ()) and self._retail(p)]
            return self.review("Hybrid sources require grade checks for every injected source and an HDR10+/L1 plot where applicable", [*occupants, *priority],
                               slot=label, why="Retail disc DV takes precedence unless the hybrid is proven superior; do not infer superiority from HDR flags or filesize.")
        retail_dv = upload.kind in {ENCODE, REMUX} and DV in (upload.hdr or ()) and self._retail(upload)
        hybrids = [p for p in family if p.hybrid]
        if retail_dv and hybrids:
            return self.review("Retail disc DV normally trumps hybrid sources; check whether the hybrid has a proven superior-quality exception", hybrids, slot=label)
        quality = upload.resolution == "1080p" and upload.kind == ENCODE and upload.codec == H264
        if quality and len(occupants) == 1 and not is_repack_of(upload, occupants[0]):
            ratio = size_diff_ratio(upload, occupants[0])
            if ratio is None or ratio >= 0.20:
                return self.review("The second x264 slot must be a genuine Quality/Retention alternative; a 20% size gap does not prove quality", occupants, slot=label)
        result = self.by_slot(upload, family, self.key, label, trump=self._trump,
                              coexists=(lambda a, b: (size_diff_ratio(a, b) or 0) >= 0.20) if quality else None,
                              capacity=2 if quality else 1)
        if upload.internal and result.verdict is Verdict.BLOCK:
            return self.review("Internals may coexist in an additional slot or trump only when equivalent/superior; verify quality, not internal status alone", occupants, slot=label)
        return result

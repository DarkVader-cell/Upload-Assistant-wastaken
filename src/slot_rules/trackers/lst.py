# Upload Assistant © 2026 Audionut & wastaken7 — Licensed under UAPL v1.0
"""LST slots (Upload Rules, Slots & Trumping, transcribed 2026-10-15)."""

from collections.abc import Sequence
from dataclasses import replace
from datetime import date

from src.meta import Meta
from src.slot_rules.base import SlotKey, SlotRules, UnknownTraitError, add_context, edition_text, is_repack_of, slot_label
from src.slot_rules.models import SlotDecision, Verdict
from src.slot_rules.profile import AV1, DISC, DV, DVDRIP, ENCODE, H264, H265, HDR10P, REMUX, SD, WEBDL, WEBRIP, ReleaseProfile, has_unrecognized_cut_claim

UNLISTED = "unlisted"


class _LstSlotLayout(SlotRules):
    TRACKER = "LST"

    def web_range(self, profile: ReleaseProfile) -> str:
        hdr = self.require(profile.hdr, "dynamic range")
        if not hdr:
            return "SDR"
        if hdr == {DV}:
            return "DV"
        if HDR10P in hdr:
            return "HDR10+"
        return "HDR"

    def key(self, profile: ReleaseProfile) -> SlotKey:
        res = self.require(profile.resolution, "resolution")
        kind = self.require(profile.kind, "release type")
        edition = (profile.edition & {"directors", "extended", "uncut", "unrated", "final_cut", "open_matte"}, profile.is_3d)
        if kind in (WEBDL, WEBRIP):
            provider = self.require(profile.provider, "streaming provider")
            codec = self.require(profile.codec, "video codec")
            label = "WEBRip" if kind == WEBRIP else "WEB-DL"
            if res == SD:
                return (res, label, provider, edition)
            if res == "720p":
                return (res, label, provider, edition) if codec == H264 else (res, UNLISTED, kind)
            allowed = {H264, H265} if res == "1440p" else {H264, H265, AV1}
            if res not in {"1080p", "1440p", "2160p"} or codec not in allowed:
                return (res, UNLISTED, kind)
            web_range = self.web_range(profile)
            if web_range != "SDR" and codec != H265:
                return (res, UNLISTED, kind)
            return (res, label, provider, codec if web_range == "SDR" else web_range, edition)
        if kind == REMUX:
            if res == "2160p":
                hdr = self.require(profile.hdr, "dynamic range")
                return (res, "Remux", "SDR" if not hdr else ("hybrid" if profile.hybrid else "DV/HDR"), edition)
            return (res, "Remux", edition) if res in (SD, "1080p") else (res, UNLISTED, kind)
        if kind == ENCODE:
            codec = self.require(profile.codec, "video codec")
            if res in (SD, "720p"):
                return (res, "encode", edition) if codec == H264 else (res, UNLISTED, kind)
            if codec not in (H264, H265, AV1) or (res == "2160p" and codec == H264):
                return (res, UNLISTED, kind)
            hdr = self.require(profile.hdr, "dynamic range")
            if hdr and codec == H264:
                return (res, UNLISTED, kind)
            return (res, "encode", codec, self.web_range(profile), edition)
        return (res, UNLISTED, kind)

    def decide(self, upload: ReleaseProfile, existing: Sequence[ReleaseProfile]) -> SlotDecision | None:
        upload_key = self.key(upload)
        if isinstance(upload_key, tuple) and UNLISTED in upload_key:
            return self.decision(Verdict.REVIEW, "LST's slot list has no place for this kind of release.", why="Open a support ticket if an additional slot is justified.")

        if upload.kind == WEBRIP:
            same_webdl = [profile for profile in existing if profile.kind == WEBDL and profile.resolution == upload.resolution and profile.provider == upload.provider]
            if same_webdl:
                return self.decision(
                    Verdict.REVIEW,
                    "A WEB-DL from the same provider is already on the site.",
                    same_webdl,
                    why="A WEBRip only gets a slot beside the WEB-DL when comparisons show a clear visual improvement.",
                )

        notes: list[str] = []
        if upload.resolution == SD:
            notes.append("SD is only allowed when no equivalent HD retail source exists.")

        def trump(new: ReleaseProfile, old: ReleaseProfile) -> tuple[Verdict, str]:
            if old.internal and not (new.internal and new.group and new.group == old.group):
                return Verdict.BLOCK, "It is an internal release; only its own group can replace it."
            if is_repack_of(new, old):
                return Verdict.ALLOW, "A REPACK/PROPER replaces the original release from the same group."
            if new.kind == ENCODE:
                return Verdict.REVIEW, "Encodes can coexist when they are clearly different in quality, size or source master."
            if new.kind == WEBDL and old.kind == WEBRIP:
                return Verdict.REVIEW, "A WEBRip that was proven better than the WEB-DL keeps its slot."
            if new.resolution == "2160p" and new.kind == WEBDL and new.audio_lossless and not old.audio_lossless:
                return Verdict.REVIEW, "There is one extra 2160p WEB-DL slot for lossless audio, from any provider."
            return self.hdr_trump(new, old)

        return self.by_slot(upload, existing, self.key, slot_label(upload_key), trump=trump, notes=notes)


class LstSlotRules(_LstSlotLayout):
    """Priority-aware recommendations; internal protection is not a quality claim."""
    RULES_DATE = date(2026, 10, 19)
    CUTS = frozenset({"directors", "extended", "uncut", "unrated", "final_cut"})

    def decision(self, verdict, reason, conflicts=(), notes=(), *, slot="", why=""):
        result = super().decision(verdict, reason, conflicts, notes, slot=slot, why=why)
        result.requires_evidence = verdict is Verdict.REVIEW
        return result

    def key(self, profile):
        if profile.kind == DVDRIP:
            profile = replace(profile, kind=ENCODE)
        if profile.kind == REMUX and profile.resolution == "2160p" and profile.hybrid:
            if not (profile.hdr and profile.hdr & {DV, HDR10P}):
                return super().key(replace(profile, hybrid=False))
            web_layers = profile.entry.get("hybrid_web_layers")
            if profile is getattr(self, "_candidate", None) and isinstance(self.meta, Meta):
                web_layers = self.meta.get("LST_web_hybrid_layers", web_layers)
            if web_layers is False:
                return super().key(replace(profile, hybrid=False))
            if web_layers is not True:
                raise UnknownTraitError("A HYBRID label alone does not establish WEB-sourced layers for the dedicated remux slot")
        return super().key(profile)

    @staticmethod
    def _same_group_internal(new, old):
        return bool(new.internal and new.group and old.group and new.group == old.group)

    def _can_replace_internal(self, new, old):
        if not self._same_group_internal(new, old):
            return False
        try:
            return self.key(new) == self.key(old)
        except UnknownTraitError:
            return False

    def _family(self, new, old):
        cuts = self.CUTS | {"open_matte"}
        if new.is_3d != old.is_3d or (new.edition & cuts) != (old.edition & cuts):
            return False
        if old.resolution not in {None, "OTHER", new.resolution}:
            return False
        if old.kind is not None and old.kind != new.kind:
            return False
        if new.kind in {WEBDL, WEBRIP} and new.provider and old.provider and new.provider != old.provider:
            return False
        if new.kind in {WEBDL, WEBRIP, ENCODE} and new.codec and old.codec and new.codec != old.codec:
            return False
        dynamic = new.kind in {WEBDL, WEBRIP, ENCODE} or (new.kind == REMUX and new.resolution == "2160p")
        return not (dynamic and new.hdr is not None and old.hdr is not None and bool(new.hdr) != bool(old.hdr))

    def evaluate(self, upload, existing):
        from src.slot_rules.trackers.lst_requirements import lst_requirements
        web_claim = isinstance(self.meta, Meta) and self.meta.get("LST_web_hybrid_layers") is True
        upload = replace(upload, hybrid=upload.hybrid or upload.entry.get("hybrid") is True or web_claim)
        existing = [replace(p, hybrid=p.hybrid or p.entry.get("hybrid") is True or p.entry.get("hybrid_web_layers") is True) for p in existing]
        self._candidate = upload
        self._all_releases = existing
        blocked, self._required = lst_requirements(upload, self.meta, existing)
        protected = [str(p.entry['id']) for p in existing if p.internal and not self._can_replace_internal(upload, p) and p.entry.get('id')]
        if blocked:
            result = self.decision(Verdict.BLOCK, blocked)
            result.constraint_violation = True
        elif upload.kind == DISC:
            exact = [p for p in existing if p.exact]
            result = self.decision(Verdict.BLOCK, "This exact disc is already listed", exact) if exact else self.decision(
                Verdict.REVIEW, "Unlimited full-disc slots require different content/region and complete retail packaging; other formats cannot trump a full disc",
                why=" ".join(self._required))
        else:
            result = super().evaluate(upload, existing)
        if result is not None:
            result.protected_ids = protected
            if result.verdict is Verdict.REVIEW:
                shown = result.why + " " + " ".join(result.notes)
                result.notes.extend(note for note in self._required if note not in shown)
            if result.verdict is Verdict.ALLOW:
                result.notes.append("Verify actual content/source/audio/subtitle compliance; internal status, filesize and flags alone are not quality proof.")
        return result

    def decide(self, upload, existing):
        key = self.key(upload)
        label = slot_label(key) + (" · 3D" if upload.is_3d else "")
        if UNLISTED in key:
            return self.decision(Verdict.REVIEW, "No listed LST slot covers this format; verify an exception/support ticket", why=" ".join(self._required))
        possible = [p for p in existing if p.resolution in {None, "OTHER", upload.resolution} and (p.kind is None or p.kind == upload.kind)]
        if has_unrecognized_cut_claim(edition_text(upload)):
            return add_context(self.decision(Verdict.REVIEW, "The incoming edition claims an unrecognized cut; LST needs actual content-difference evidence before using an extra slot", slot=label,
                                             why="The supplied LST rules recognize only documented alternate cuts; marketing/source labels do not create slots."), possible,
                               "Possible same-format release; context only, not a trump/report target.")
        ambiguous = [p for p in possible if has_unrecognized_cut_claim(edition_text(p))]
        if ambiguous:
            return add_context(self.decision(Verdict.REVIEW, "A relevant LST release has an unrecognized cut claim; occupancy needs manual comparison", slot=label), ambiguous,
                               "This may be a substantive cut or a marketing label; do not infer a separate slot.")
        family = [p for p in existing if self._family(upload, p)]
        holders = []
        for old in family:
            try:
                if self.key(old) == key:
                    holders.append(old)
            except UnknownTraitError:
                pass
        protected = [p for p in holders if p.internal and not self._same_group_internal(upload, p)]
        if protected:
            return self.decision(Verdict.REVIEW, "The existing internal cannot be trumped by another group; coexistence needs a directly superior non-internal or justified internal release", protected,
                                 slot=label, why="Internal Trumpable tags and dead status never remove protection. Equivalent internal/back-catalogue releases may coexist; quality and benefit must be checked. " + " ".join(self._required))
        webdl = [p for p in existing if p.kind == WEBDL and p.resolution == upload.resolution and p.provider == upload.provider and p.hdr == upload.hdr]
        if upload.kind == WEBRIP and webdl:
            return add_context(self.decision(Verdict.REVIEW, "WEBRip may earn an additional slot only with clear visual-improvement comparisons; it never trumps the WEB-DL", slot=label,
                                 why="An already proven WEBRip also remains when WEB-DL arrives. " + " ".join(self._required)),webdl,'Compare against this source WEB-DL. It is not a WEBRip trump target.')
        if upload.resolution == SD:
            hd = [p for p in self._all_releases if p.resolution in {"720p", "1080p", "1440p", "2160p"} and (p.edition & self.CUTS) == (upload.edition & self.CUTS)]
            if hd:
                return add_context(self.decision(Verdict.BLOCK, "Equivalent HD retail sources preclude SD non-disc uploads; verify actual source equivalence"),hd,'This HD source affects SD eligibility; verify equivalence rather than treating it as an SD replacement target.')
            return self.decision(Verdict.REVIEW, "Confirm there are no equivalent HD retail sources; DVD Remux can replace DVDRip only absent a superior-video exception", slot=label, why=" ".join(self._required))
        cuts = [p for p in existing if p.kind == upload.kind and p.resolution == upload.resolution and (p.edition & self.CUTS) != (upload.edition & self.CUTS)]
        if cuts:
            return add_context(self.decision(Verdict.REVIEW, "Alternate-cut content differences must be documented before claiming an extra slot", slot=label, why=" ".join(self._required)),cuts,'Document actual cut/content differences from this listed release; an alternate cut is not automatically a trump target.')
        if upload.kind == REMUX and (upload.hybrid or any(p.hybrid for p in family)):
            native_dv = DV in (upload.hdr or ()) and not upload.hybrid
            related = [p for p in family if (native_dv and p.hybrid) or (upload.hybrid and not p.hybrid and DV in (p.hdr or ()))]
            return self.decision(Verdict.REVIEW, "Verify hybrid WEB-layer grade/plot and native-disc DV priority, including a proven-superior hybrid exception", [*holders, *related],
                                 slot=label, why="WEB-layer provenance and correct splices must be demonstrated; flags cannot prove them. " + " ".join(self._required))
        if isinstance(self.meta, Meta) and (self.meta.extras or self.meta.get("LST_back_catalogue") is True):
            return self.decision(Verdict.REVIEW, "Verify extra-slot justification/back-catalogue coexistence; internal status alone does not justify a trump", slot=label, why=" ".join(self._required))
        dead = [p for p in holders if p.entry.get("dead") is True or ("seeders" in p.entry and str(p.entry['seeders']) == "0")]
        if dead:
            return self.decision(Verdict.REVIEW, "A no-seeder torrent may be replaced only by an equivalent/better release; internal protection still applies", dead,
                                 slot=label, why=" ".join(self._required))
        if self._required:
            return self.decision(Verdict.REVIEW, "Verify required LST source, container, audio/subtitle and screenshot evidence", holders, slot=label, why=" ".join(self._required))
        lossless = upload.kind == WEBDL and upload.resolution == "2160p" and upload.audio_lossless
        if (lossless and holders and not all(is_repack_of(upload, p) for p in holders)
                and any(p.kind == WEBDL and p.resolution == "2160p" and p.audio_lossless for p in existing)):
            return self.decision(Verdict.REVIEW, "Only one extra 2160p lossless WEB-DL slot exists across providers; verify the best/most-complete candidate", holders, slot=label)
        if upload.kind == REMUX and holders and not all(self.hdr_trump(upload, p)[0] is Verdict.ALLOW for p in holders):
            return self.decision(Verdict.REVIEW, "Remuxes may coexist for documented different masters, or trump for superior sources/assets or confirmed defects", holders,
                                 slot=label, why="Verify original mixes, English dub, retail named chapters/subtitles and actual fixes; no source or quality advantage is inferred from size.")
        result = super().decide(upload, family)
        if upload.internal and result is not None and result.verdict is Verdict.BLOCK:
            return self.decision(Verdict.REVIEW, "Internal release may coexist if equivalent or superior; demonstrate benefit, not internal status alone", holders, slot=label)
        return result

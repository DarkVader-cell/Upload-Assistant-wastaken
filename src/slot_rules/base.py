# Upload Assistant © 2026 Audionut & wastaken7 — Licensed under UAPL v1.0
"""Shared machinery for tracker slot rules."""

import re
from collections.abc import Callable, Sequence
from datetime import date
from typing import Any, ClassVar

from src.cogs.redaction import Redaction
from src.slot_rules.links import public_detail_url
from src.slot_rules.models import SlotDecision, Verdict
from src.slot_rules.profile import DISC, DV, HDR10, HDR10P, HLG, PQ10, WEBDL, WEBRIP, ReleaseProfile

# Rules transcribed from the tracker pages on this date.
RULES_DATE_2026_10_15 = date(2026, 10, 15)

type SlotKey = tuple[object, ...]
# Returns a verdict and reason when the upload competes with an occupant of its slot.
type TrumpTest = Callable[[ReleaseProfile, ReleaseProfile], tuple[Verdict, str]]


class UnknownTraitError(Exception):
    """A trait the rule needs could not be determined; the user has to decide."""


def hdr_rank(profile: ReleaseProfile) -> int:
    """Rank HDR packages within one HDR slot: DV+HDR10+ > DV+HDR10 / HDR10+ > HDR10 > PQ10."""
    hdr = profile.hdr or frozenset()
    if DV in hdr and HDR10P in hdr:
        return 4
    if (DV in hdr and HDR10 in hdr) or HDR10P in hdr:
        return 3
    if HDR10 in hdr:
        return 2
    if PQ10 in hdr or HLG in hdr:
        return 1
    return 0


def expanded_hdr(profile: ReleaseProfile) -> frozenset[str]:
    """HDR flags including implied layers: HDR10+ always carries an HDR10 base layer."""
    hdr = profile.hdr or frozenset()
    return hdr | {HDR10} if HDR10P in hdr else hdr


def size_diff_ratio(first: ReleaseProfile, second: ReleaseProfile) -> float | None:
    """Size difference relative to the larger release (0.2 means 20% smaller)."""
    if not first.size or not second.size:
        return None
    larger = max(first.size, second.size)
    return abs(first.size - second.size) / larger


def _repack_traits(profile: ReleaseProfile) -> tuple[object, ...]:
    """Traits that identify a release; None means unknown. WEB releases are also identified by provider."""
    if profile.kind is None:
        provider: object = None
    elif profile.kind in (WEBDL, WEBRIP):
        provider = profile.provider
    else:
        provider = "not WEB"
    return (profile.resolution, profile.kind, profile.codec, profile.hdr, provider)


def _newer_from_same_group(upload: ReleaseProfile, existing: ReleaseProfile) -> bool:
    return bool(upload.group and upload.group == existing.group and upload.repack > existing.repack and upload.edition == existing.edition)


def is_repack_of(upload: ReleaseProfile, existing: ReleaseProfile) -> bool:
    """``upload`` is a confirmed newer REPACK/PROPER of the same release: same group, edition and format."""
    traits = zip(_repack_traits(upload), _repack_traits(existing), strict=True)
    return _newer_from_same_group(upload, existing) and all(first is not None and first == second for first, second in traits)


def may_be_repack_of(upload: ReleaseProfile, existing: ReleaseProfile) -> bool:
    """Like ``is_repack_of``, but some format traits are unknown, so it cannot be confirmed."""
    if not _newer_from_same_group(upload, existing):
        return False
    traits = list(zip(_repack_traits(upload), _repack_traits(existing), strict=True))
    has_unknown = any(first is None or second is None for first, second in traits)
    return has_unknown and all(first is None or second is None or first == second for first, second in traits)


_LABEL_WORDS = {"H264": "H.264", "H265": "H.265", "encode": "Encode", "x264 encode": "x264 Encode", "x265 encode": "x265 Encode"}


def slot_label(key: SlotKey) -> str:
    """Readable slot name from a slot key without hiding structured traits."""
    parts: list[str] = []
    for part in key:
        if isinstance(part, str) and part:
            parts.append(_LABEL_WORDS.get(part, part))
        elif isinstance(part, frozenset) and part:
            # Slot keys use frozensets for dynamic range and edition traits.
            # Keep those details visible in diagnostics instead of reducing
            # every conflict to the same generic "slot" message.
            parts.append("/".join(sorted(str(value) for value in part)))
    return " · ".join(parts)


REPACK_REASON = "A REPACK/PROPER replaces the original release from the same group."


def _entry_text(profile: ReleaseProfile, *keys: str) -> str:
    for key in keys:
        value = profile.entry.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def edition_text(profile: ReleaseProfile) -> str:
    return _entry_text(profile, "edition", "RemasterTitle") or profile.name


def profile_traits(profile: ReleaseProfile) -> str:
    """Return a bounded, structured trait summary for operator diagnostics."""
    raw_edition = _entry_text(profile, "edition", "RemasterTitle")
    edition = raw_edition or (",".join(sorted(profile.edition)) if profile.edition else "standard/unspecified edition")
    source = _entry_text(profile, "source", "Source")
    if not source:
        if re.search(r"blu[ ._-]?ray|\buhd[ ._-]?bd\b", profile.name, re.I):
            source = "Blu-ray"
        elif re.search(r"web[ ._-]?(?:dl|rip)\b", profile.name, re.I):
            source = "WEB"
        elif re.search(r"\bhdtv\b", profile.name, re.I):
            source = "HDTV"
        else:
            source = "unknown source"
    provider = _entry_text(profile, "provider", "Provider") or profile.provider
    result = (
        f"{profile.resolution or 'unknown resolution'} · {profile.kind or 'unknown format'} · "
        f"{profile.codec or 'unknown codec'} · {profile.hdr_label} · edition={edition} · source={source}"
    )
    if provider:
        result += f" · provider={provider}"
    if profile.group:
        result += f" · group={profile.group}"
    if profile.size:
        result += f" · size={profile.size} bytes"
    if profile.video_bitrate_kbps:
        result += f" · video={profile.video_bitrate_kbps:g} kb/s"
    if profile.audio_codec:
        result += f" · audio={profile.audio_codec}"
    if profile.audio_languages:
        result += " · audio languages=" + "/".join(sorted(profile.audio_languages))
    if profile.repack:
        result += f" · REPACK/PROPER generation={profile.repack}"
    if profile.hi10p:
        result += " · Hi10P (10-bit AVC)"
    if profile.internal:
        result += " · internal=yes"
    if profile.hybrid:
        result += " · hybrid"
    return result


def incoming_traits(profile: ReleaseProfile) -> str:
    return profile_traits(profile)


def _generic_traits(profile: Any) -> str:
    """Describe tracker-specific profiles without requiring video traits."""
    fields = []
    for key in ("media", "format", "encoding", "edition", "sample_rate", "bit_depth"):
        value = getattr(profile, key, None)
        if value not in (None, ""):
            fields.append(f"{key}={value}")
    return "; ".join(fields) or "tracker-specific release profile"


def describe_releases(profiles: Sequence[ReleaseProfile], reason: str, *, role: str = "context") -> list[dict[str, Any]]:
    """Safe, display-only references; not a replacement/report candidate list."""
    result = []
    for p in profiles:
        link = public_detail_url(p.entry.get("link"))
        link_note = p.entry.get("link_note") or ("No public detail URL or usable torrent identifier was supplied; check this release on the tracker." if not link else "")
        result.append(
            {
                "name": getattr(p, "name", p.entry.get("name", "unknown release")),
                "id": p.entry.get("id"),
                "size": p.entry.get("size", getattr(p, "size", None)),
                "link": link,
                "traits": profile_traits(p) if isinstance(p, ReleaseProfile) else _generic_traits(p),
                "role": role,
                **({"link_note": link_note} if link_note else {}),
                "reason": reason + (" Details unavailable: " + str(Redaction.redact_private_info(str(p.entry["detail_error"]))) if p.entry.get("detail_error") else ""),
            }
        )
    return result


def add_context(decision: SlotDecision, profiles: Sequence[ReleaseProfile], reason: str) -> SlotDecision:
    decision.related_releases.extend(describe_releases(profiles, reason, role="eligibility"))
    return decision


def pair_reasons(decision: SlotDecision, pairs: Sequence[tuple[ReleaseProfile, str]]) -> SlotDecision:
    decision.comparisons = [item for profile, reason in pairs for item in describe_releases([profile], reason or decision.reason, role="competing")]
    return decision


class SlotRules:
    """Base class: subclasses set the class attributes and implement ``decide``."""

    TRACKER: ClassVar[str] = ""
    RULES_DATE: ClassVar[date] = RULES_DATE_2026_10_15

    def __init__(self, meta: Any = None) -> None:
        # Upload metadata, for rules that use tracker data stored during the search.
        self.meta = meta

    def decision(
        self,
        verdict: Verdict,
        reason: str,
        conflicts: Sequence[ReleaseProfile] = (),
        notes: Sequence[str] = (),
        *,
        slot: str = "",
        why: str = "",
    ) -> SlotDecision:
        details = list(notes)
        candidate = getattr(self, "_candidate", None)
        if isinstance(candidate, ReleaseProfile) and not any("incoming:" in note.casefold() for note in details):
            details.insert(0, f"Incoming: {incoming_traits(candidate)}.")
        return SlotDecision(
            verdict=verdict,
            reason=reason,
            tracker=self.TRACKER,
            rules_date=self.RULES_DATE,
            slot=slot,
            why=why,
            conflicts=[dict(conflict.entry) for conflict in conflicts],
            comparisons=describe_releases(conflicts, why or reason, role="competing"),
            notes=details,
        )

    def evaluate(self, upload: ReleaseProfile, existing: Sequence[ReleaseProfile]) -> SlotDecision | None:
        """Return a recommendation, or ``None`` to leave the decision to the basic dupe check."""
        if upload.kind == DISC:
            return None
        self._candidate = upload
        exact = [profile for profile in existing if profile.exact]
        if exact:
            return self.decision(Verdict.BLOCK, "This exact release is already on the site.", exact,
                                 why=f"The tracker returned an exact named-release match for {upload.name}. Changing upload flags does not create a separate slot.")
        newer = [profile for profile in existing if is_repack_of(profile, upload)]
        if newer:
            pairs = [(profile, f"Same group ({upload.group}) and matching edition/format; site generation {profile.repack} is newer than incoming generation {upload.repack}.") for profile in newer]
            return pair_reasons(self.decision(Verdict.BLOCK, "A newer REPACK/PROPER of this release is already on the site.", newer, why=pairs[0][1]), pairs)
        possibly_newer = [profile for profile in existing if may_be_repack_of(profile, upload)]
        if possibly_newer:
            pairs = []
            labels = ("resolution", "release type", "video codec", "dynamic range", "streaming provider")
            for profile in possibly_newer:
                missing = [label for label, incoming, old in zip(labels, _repack_traits(upload), _repack_traits(profile), strict=True) if incoming is None or old is None]
                pairs.append((profile, f"Same group ({upload.group}) and a higher REPACK/PROPER generation, but missing {', '.join(missing)} prevents confirming the same release format."))
            return pair_reasons(self.decision(
                Verdict.REVIEW,
                "A newer REPACK/PROPER from the same group may already be on the site.",
                possibly_newer,
                why=pairs[0][1],
            ), pairs)
        try:
            return self.decide(upload, [profile for profile in existing if profile.kind != DISC])
        except UnknownTraitError as e:
            return self.decision(Verdict.REVIEW, "This check is missing a detail it needs.", why=str(e))

    def decide(self, upload: ReleaseProfile, existing: Sequence[ReleaseProfile]) -> SlotDecision | None:
        raise NotImplementedError

    @staticmethod
    def require[T](value: T | None, what: str) -> T:
        if value is None:
            raise UnknownTraitError(f"Could not determine the {what}.")
        return value

    def by_slot(
        self,
        upload: ReleaseProfile,
        existing: Sequence[ReleaseProfile],
        key: Callable[[ReleaseProfile], SlotKey | None],
        label: str,
        *,
        trump: TrumpTest | None = None,
        coexists: Callable[[ReleaseProfile, ReleaseProfile], bool] | None = None,
        capacity: int = 1,
        notes: Sequence[str] = (),
    ) -> SlotDecision:
        """Decide using a slot key: releases with the same key compete for ``capacity`` places.

        ``key`` returns ``None`` when the release has no slot (it never competes).
        It may raise ``UnknownTraitError``; for the upload that makes the result REVIEW,
        for an existing release the unknown entries are listed for review.
        """
        upload_key = key(upload)
        if upload_key is None:
            return self.decision(Verdict.ALLOW, "This kind of release has no slot limit on this tracker.", notes=notes,
                                 why=f"{self.TRACKER}'s slot mapping does not limit {upload.resolution or 'unknown resolution'} {upload.kind or 'unknown type'}. This is not an exemption from its other content or quality rules.")

        occupants: list[ReleaseProfile] = []
        unknown: list[ReleaseProfile] = []
        missing: list[tuple[ReleaseProfile, str]] = []
        for profile in existing:
            # When the key explicitly starts with the exact resolution, an
            # independently known different resolution cannot occupy it.
            if upload_key and upload_key[0] == upload.resolution and profile.resolution and profile.resolution != upload.resolution:
                continue
            try:
                if key(profile) == upload_key:
                    occupants.append(profile)
            except UnknownTraitError as error:
                unknown.append(profile)
                missing.append((profile, str(error)))

        def uncertain_allow(provisional: SlotDecision) -> SlotDecision:
            if not unknown:
                return provisional
            why = " ".join(dict.fromkeys(reason for _, reason in missing))
            result = self.decision(Verdict.REVIEW, f"The {label} slot cannot be confirmed: {len(unknown)} existing release(s) lack required comparison details.", unknown,
                                   provisional.notes, slot=label, why=why)
            result.requires_evidence = True
            result.requirements = ["Classify the linked incomplete releases before treating this slot as vacant or reporting a trump."]
            result.related_releases = describe_releases(occupants, "Known comparison only; replacement eligibility is provisional until the incomplete releases are classified.")
            return pair_reasons(result, missing)

        if not occupants:
            if unknown:
                return uncertain_allow(self.decision(Verdict.ALLOW, f"No confirmed occupant of {label}.", notes=notes, slot=label))
            return self.decision(Verdict.ALLOW, f"No release on the {label} slot is listed on the site yet.", notes=notes, slot=label)

        competing = [profile for profile in occupants if not (coexists and coexists(upload, profile))]
        if not competing:
            if len(occupants) >= capacity:
                return self.decision(Verdict.BLOCK, f"All {capacity} places in this slot are already taken.", occupants, notes, slot=label,
                                     why=f"{self.TRACKER} permits at most {capacity} coexisting releases in {label}; {len(occupants)} are already listed. The coexistence exception does not open another place beyond that limit.")
            return uncertain_allow(self.decision(
                Verdict.ALLOW,
                f"There is still room in the {label} slot, and your release is different enough from the one there.",
                notes=notes,
                slot=label,
            ))

        test = trump or self.default_trump
        results = []
        for profile in competing:
            verdict, reason = test(upload, profile)
            if not reason:
                reason = (f"{self.TRACKER}: both releases occupy {label}; no permitted replacement or coexistence exception was established. "
                          f"Incoming: {profile_traits(upload)}. Existing: {profile_traits(profile)}.")
            if upload.size and profile.size and upload.size > 0 and profile.size > 0:
                ratio = max(upload.size, profile.size) / min(upload.size, profile.size)
                difference = 100 * abs(upload.size - profile.size) / max(upload.size, profile.size)
                reason += f" Measured sizes: incoming {upload.size} bytes; existing {profile.size} bytes; {difference:.2f}% of the larger file, larger/smaller={ratio:.4f}."
            results.append((profile, verdict, reason))
        blocking = [(profile, reason) for profile, verdict, reason in results if verdict is Verdict.BLOCK]
        if blocking:
            why = next((reason for _, reason in blocking if reason), "")
            return pair_reasons(
                self.decision(Verdict.BLOCK, f"Another release already fills the {label} slot.", [profile for profile, _ in blocking], notes, slot=label, why=why), blocking
            )
        reviewing = [(profile, reason) for profile, verdict, reason in results if verdict is Verdict.REVIEW]
        if reviewing:
            return pair_reasons(
                self.decision(
                    Verdict.REVIEW,
                    f"Another release occupies the {label} slot, but yours might still be accepted.",
                    [profile for profile, _ in reviewing],
                    notes,
                    slot=label,
                    why=reviewing[0][1],
                ),
                reviewing,
            )
        reasons = " ".join(dict.fromkeys(reason for _, _, reason in results if reason))
        decision = self.decision(
            Verdict.ALLOW,
            f"Your release can replace the one in the {label} slot. Report it as a trump after uploading.",
            competing,
            notes,
            slot=label,
            why=reasons,
        )
        decision.trump_recommended = True
        return uncertain_allow(pair_reasons(decision, [(profile, reason) for profile, _verdict, reason in results]))

    @staticmethod
    def default_trump(upload: ReleaseProfile, existing: ReleaseProfile) -> tuple[Verdict, str]:
        if is_repack_of(upload, existing):
            return Verdict.ALLOW, REPACK_REASON
        if may_be_repack_of(upload, existing):
            return Verdict.REVIEW, "The newer same-group REPACK/PROPER may qualify, but incomplete format/provider metadata prevents confirming that it replaces this exact release."
        return Verdict.BLOCK, (f"Replacement requires a newer same-group, same-edition, same-format REPACK/PROPER. "
                               f"Incoming generation={upload.repack}, site generation={existing.repack}; "
                               f"incoming group={upload.group or 'unknown'}, site group={existing.group or 'unknown'}. The full replacement conditions are not established.")

    @staticmethod
    def hdr_trump(upload: ReleaseProfile, existing: ReleaseProfile) -> tuple[Verdict, str]:
        """Repack, or a strictly broader HDR package (for example DV/HDR over HDR), trumps."""
        if is_repack_of(upload, existing):
            return Verdict.ALLOW, REPACK_REASON
        if upload.hdr is None or existing.hdr is None:
            return Verdict.REVIEW, "Cannot compare the HDR replacement: one release has no confirmed dynamic-range metadata. Check MediaInfo before deciding."
        if hdr_rank(upload) > hdr_rank(existing) and expanded_hdr(existing) <= expanded_hdr(upload):
            return Verdict.ALLOW, f"{upload.hdr_label} takes priority over {existing.hdr_label} in this slot."
        return Verdict.BLOCK, f"Incoming {upload.hdr_label} does not provide a strictly higher, compatible superset of existing {existing.hdr_label}; it is not a qualifying same-group REPACK/PROPER either."

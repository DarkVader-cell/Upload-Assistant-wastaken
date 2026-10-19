# Upload Assistant © 2026 Audionut & wastaken7 — Licensed under UAPL v1.0
"""Entry point that turns a tracker's search results into a slot recommendation."""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any, cast

from src.console import logger
from src.dupe_checking import DupeChecker, DupeInput
from src.meta import Meta
from src.region import get_service
from src.slot_rules.base import SlotRules
from src.slot_rules.models import SlotDecision, Verdict
from src.slot_rules.profile import DISC, ReleaseProfile, group_from_name, profile_from_entry, profile_from_meta
from src.slot_rules.trackers.aither import AitherSlotRules
from src.slot_rules.trackers.anthelion import AnthelionSlotRules
from src.slot_rules.trackers.avistaz import AvistaZSlotRules, CinemaZSlotRules, PrivateHDSlotRules
from src.slot_rules.trackers.brazilian import CapybaraBRSlotRules, SamaritanoSlotRules
from src.slot_rules.trackers.cathoderaytube import CathodeRayTubeSlotRules
from src.slot_rules.trackers.greatposterwall import GreatPosterWallSlotRules
from src.slot_rules.trackers.hdbits import HDBitsSlotRules
from src.slot_rules.trackers.hdtorrents import HDTorrentsSlotRules
from src.slot_rules.trackers.lst import LstSlotRules
from src.slot_rules.trackers.luminarr import LuminarrSlotRules
from src.slot_rules.trackers.passthepopcorn import PassThePopcornSlotRules
from src.slot_rules.trackers.simple import DreadVaultSlotRules, MTeamSlotRules, SeedpoolSlotRules, TorrentLeechSlotRules
from src.slot_rules.trackers.ulcx import UlcxSlotRules
from src.slot_rules.trackers.webproviders import HomieHelpDeskSlotRules, SkipTheCommercialsSlotRules

SLOT_RULES: dict[str, type[SlotRules]] = {
    rules.TRACKER: rules
    for rules in (
        AitherSlotRules,
        AnthelionSlotRules,
        AvistaZSlotRules,
        CapybaraBRSlotRules,
        CathodeRayTubeSlotRules,
        CinemaZSlotRules,
        DreadVaultSlotRules,
        GreatPosterWallSlotRules,
        HDBitsSlotRules,
        HDTorrentsSlotRules,
        HomieHelpDeskSlotRules,
        LstSlotRules,
        LuminarrSlotRules,
        MTeamSlotRules,
        PassThePopcornSlotRules,
        PrivateHDSlotRules,
        SamaritanoSlotRules,
        SeedpoolSlotRules,
        SkipTheCommercialsSlotRules,
        TorrentLeechSlotRules,
        UlcxSlotRules,
    )
}

SLOT_CATEGORIES = frozenset({"MOVIE", "TV"})


def slot_rules_enabled(config: Mapping[str, Any]) -> bool:
    """Slot rules are on unless ``DEFAULT.slot_rules`` is explicitly false."""
    default = cast(Mapping[str, Any], config.get("DEFAULT") or {})
    return default.get("slot_rules", True) is not False


def has_slot_rules(tracker: str) -> bool:
    return tracker.upper() in SLOT_RULES


def slot_rules_apply(meta: Meta, config: Mapping[str, Any]) -> bool:
    """Whether the slot system is relevant to this upload at all (any tracker)."""
    return slot_rules_enabled(config) and meta.category in SLOT_CATEGORIES and not meta.is_disc


def _as_entry(dupe: DupeInput) -> dict[str, Any]:
    if isinstance(dupe, str):
        return {"name": dupe}
    return dict(cast(Mapping[str, Any], dupe))


async def _provider(name: str) -> str | None:
    try:
        result = await get_service(video=name, tag=group_from_name(name) or "")
    except Exception:
        return None
    service = result[0] if isinstance(result, tuple) else ""
    return service or None


async def evaluate_slots(dupes: Sequence[DupeInput], meta: Meta, tracker: str, config: Mapping[str, Any]) -> SlotDecision | None:
    """Return the tracker's slot recommendation, or ``None`` to use the basic dupe check.

    ``dupes`` must be the unfiltered search results: the basic filter drops
    releases that matter for slots (other HDR layers, codecs and so on).
    """
    tracker = tracker.upper()
    rules_cls = SLOT_RULES.get(tracker)
    applies = slot_rules_apply(meta, config) or (slot_rules_enabled(config) and
              (tracker in {"PASSTHEPOPCORN", "HDBITS", "LST"} or (tracker == "AITHER" and meta.category in SLOT_CATEGORIES)))
    if rules_cls is None or not applies:
        return None
    # Trackers that search the whole title keep the full list for slot rules.
    title_releases = meta.get(f"{tracker}_title_releases")
    if isinstance(title_releases, list):
        dupes = cast(list[DupeInput], title_releases)
    try:
        upload = profile_from_meta(meta)
        if upload.kind == DISC and tracker not in {"PASSTHEPOPCORN", "AITHER", "HDBITS", "LST"}:
            return None
        if tracker in {"AITHER", "HDBITS", "LST"}:
            tracker_config = cast(Mapping[str, Any], cast(Mapping[str, Any], config.get("TRACKERS") or {}).get(tracker) or {})
            groups = tracker_config.get("internal_groups") or []
            allowed = {str(group).lstrip("-").casefold() for group in groups} if isinstance(groups, (list, tuple, set)) else set()
            upload = replace(upload, internal=bool(upload.group) and tracker_config.get("internal") is True and (upload.group or "").casefold() in allowed)
            if tracker == "LST":
                meta["LST_modq_effective"] = bool(meta.modq or tracker_config.get("modq"))

        existing: list[ReleaseProfile] = []
        season_packs: list[ReleaseProfile] = []
        for dupe in dupes:
            entry = _as_entry(dupe)
            name = str(entry.get("name") or "")
            if not name:
                continue
            if meta.category == "TV" and tracker != "PASSTHEPOPCORN":
                normalized = await DupeChecker.normalize_filename(name)
                matches, is_season_pack = await DupeChecker.is_season_episode_match(normalized, meta.season, meta.episode)
                if not matches:
                    continue
                if is_season_pack and meta.episode and not meta.tv_pack:
                    season_packs.append(profile_from_entry(entry))
                    continue
            exact = await DupeChecker.is_exact_match(entry, meta) or name.strip().lower() == (meta.name or "").strip().lower()
            existing.append(profile_from_entry(entry, provider=None if tracker == "PASSTHEPOPCORN" else await _provider(name), exact=exact))

        rules = rules_cls(meta)
        decision = rules.evaluate(upload, existing)
        # Episodes on the site decide first; a season pack only adds a review when nothing blocks.
        if season_packs and (decision is None or decision.verdict is not Verdict.BLOCK):
            conflicts = [*season_packs, *(profile for profile in existing if decision and profile.entry in decision.conflicts)]
            prior = decision
            decision = rules.decision(Verdict.REVIEW, "A season pack that contains this episode is already on the site.", conflicts)
            if prior is not None:
                decision.protected_ids = list(prior.protected_ids)
            if tracker == "LST":
                decision.protected_ids.extend(str(p.entry['id']) for p in season_packs if p.internal and p.entry.get('id'))
            if tracker in {"AITHER", "HDBITS", "LST"} and prior is not None and prior.verdict is Verdict.REVIEW:
                decision.notes.extend([prior.reason, *([prior.why] if prior.why else []), *prior.notes])
        if meta.debug:
            logger.debug(f"[slot rules] {tracker}: upload={upload}")
            logger.debug(f"[slot rules] {tracker}: decision={decision}")
        return decision
    except Exception as e:
        if tracker in {"PASSTHEPOPCORN", "AITHER", "HDBITS", "LST"}:
            logger.warning(f"{tracker}: slot evaluation failed; manual review is required.", extra={"markup": False})
            label = "PTP" if tracker == "PASSTHEPOPCORN" else tracker
            decision = rules_cls(meta).decision(Verdict.REVIEW, f"{label} slot evaluation failed; do not assume the slot is free")
            decision.requires_evidence = tracker in {"AITHER", "HDBITS", "LST"}
            return decision
        # Other trackers retain their existing basic-check fallback.
        logger.warning(f"{tracker}: slot rules could not be evaluated ({e}); using the basic dupe check.", extra={"markup": False})
        return None

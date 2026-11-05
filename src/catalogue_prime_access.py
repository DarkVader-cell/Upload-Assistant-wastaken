"""Fail-closed classification of authenticated native Prime title-information.

This is not a public FLATRATE classifier. The native adapter must stop before
manifest/license/media requests. No envelopes or account data leave this function.
"""

from __future__ import annotations


def classify(resource, *, imdb, item, country, expected_country, verified_aliases=()):
    unknown = {"state": "unknown", "reason": "No verified subscription-only full-title offer"}
    if not isinstance(resource, dict) or resource.get("imdbTconst") != imdb:
        return {"state": "unknown", "reason": "Native title identity did not match the canonical IMDb"}
    if not isinstance(country, str) or not isinstance(expected_country, str) or country.upper() != expected_country.upper():
        return {"state": "unknown", "reason": "Native account profile region did not match the search region"}
    aliases = {value for value in (item, resource.get("gti"), *verified_aliases) if isinstance(value, str) and value}
    actions = []
    for field in ("primaryActions", "actions", "adaptiveActions"):
        values = resource.get(field, [])
        if isinstance(values, list):
            actions.extend(values)
    seen = set()
    index = 0
    paid = False
    while index < len(actions) and index < 150:
        action = actions[index]
        index += 1
        if not isinstance(action, dict) or id(action) in seen:
            continue
        seen.add(id(action))
        children = action.get("childActions", [])
        if isinstance(children, list):
            actions.extend(children[:150])
        navigation = action.get("navigationAction") or {}
        metadata = navigation.get("playbackMetadata") if isinstance(navigation, dict) else None
        metadata = metadata or action.get("metadata")
        if not isinstance(metadata, dict) or metadata.get("metadataActionType") != "Playback":
            continue
        if metadata.get("videoMaterialType") != "Feature" or metadata.get("isTrailer") is True:
            continue
        # A trailer, another title, or a generic playback envelope is not evidence.
        playback_title = metadata.get("playbackTitle")
        if playback_title is None:
            # Native full-Feature actions omit playbackTitle; the enclosing
            # exact-IMDb resource must itself match the requested canonical GTI.
            if not isinstance(item, str) or not item.startswith("amzn1.dv.gti.") or resource.get("gti") != item:
                continue
        elif not isinstance(playback_title, str) or playback_title not in aliases:
            continue
        entitlement = metadata.get("userEntitlementMetadata") or {}
        if not isinstance(entitlement, dict):
            continue
        kind = entitlement.get("entitlementType")
        if kind in {"RENTAL", "PURCHASE", "OWNED", "CHANNEL_SUBSCRIPTION", "TVOD"}:
            paid = True
            continue
        experience = metadata.get("playbackExperienceMetadata") or {}
        if not isinstance(experience, dict) or not experience.get("playbackEnvelope"):
            continue
        if kind != "PRIME_SUBSCRIPTION" or metadata.get("isUnopenedRental") is True:
            continue
        # Unknown extra-benefit semantics are not silently assumed to be Prime.
        if entitlement.get("benefitType") not in (None, "", "PRIME", "Prime"):
            continue
        return {
            "state": "included",
            "reason": "Authenticated full Feature offer has PRIME_SUBSCRIPTION entitlement",
            "country": country.upper(),
            "imdb": imdb,
            "method": "native_prime_subscription_v1",
        }
    return {"state": "paid", "reason": "Only verified paid/owned/channel full-title access was observed"} if paid else unknown

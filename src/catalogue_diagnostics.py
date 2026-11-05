"""Explain empty batches locally; never relax filters or call external APIs."""

from __future__ import annotations

import json
import time
from collections import Counter

from src.catalogue_runner import SERVICES, selection_matches


def selection_summary(db, settings):
    selected = {name: cfg.get("region", SERVICES[name][1]) for name, cfg in settings.get("services", {}).items()}
    countries = sorted(settings.get("origin_countries", []))
    kinds = set(settings.get("media_types", ["movie"]))
    counts = Counter()
    total = 0
    now = time.time()
    if db is not None:
        for row in db.execute("SELECT candidate,status,next_check,discovered FROM jobs"):
            candidate = json.loads(row["candidate"])
            kind = candidate.get("media_type", "movie")
            service = candidate.get("service")
            total += 1
            reason = "eligible"
            if row["status"] not in {"pending", "unknown", "ready", "expanded"}:
                reason = "already_decided_or_attempted"
            elif row["next_check"] > now:
                reason = "retry_cooldown"
            elif not selection_matches(candidate, settings):
                reason = "title_year_votes_runtime_language_filters"
            elif service not in selected:
                reason = "disabled_service"
            elif candidate.get("region") != selected[service]:
                reason = "availability_region_mismatch"
            elif candidate.get("origin_countries", []) != countries:
                reason = "different_production_country_search"
            elif ("tv" if kind in {"series", "episode"} else kind) not in kinds:
                reason = "media_type_mismatch"
            elif now - row["discovered"] > settings.get("max_candidate_age_hours", 24) * 3600:
                reason = "expired_catalogue_evidence"
            if reason == "eligible" and service == "amazon" and settings.get("require_prime_inclusion"):
                from src.catalogue_access import access_state

                if access_state(db, candidate, candidate.get("job_key", candidate.get("imdb"))) != "manual_included":
                    reason = "unverified_prime_access"
            counts[reason] += 1
    return {
        "queue_total": total,
        "eligible": counts.get("eligible", 0),
        "exclusions": {key: value for key, value in counts.items() if key != "eligible"},
        "services": selected,
        "production_countries": countries,
        "criteria": {
            key: settings.get(key, 0) for key in ["min_release_year", "max_release_year", "min_imdb_votes", "max_imdb_votes", "min_runtime_minutes", "max_runtime_minutes"]
        },
        "external_api_requests": 0,
        "filters_relaxed": False,
        "message": "No queued titles match the active search. This is an empty selection, not a provider failure."
        if not counts.get("eligible")
        else "Matching queued titles are available; a tracker gap is not guaranteed.",
    }

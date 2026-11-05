"""Metadata-verified movies, TV expansion, and conservative free-slot jobs."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from src.catalogue_metadata import MetadataProbe, MetadataStopError, PlaybackUnavailableError, episodes_from_listing
from src.catalogue_runner import SERVICES, RunnerError, cardinal_command, selection_matches, verify_original_language
from src.catalogue_slots import SlotChecker, eligible
from src.catalogue_store import Store, job_key


def emit(candidate, status, reason="", **fields):
    print(json.dumps({"imdb": candidate.get("imdb"), "job_key": candidate.get("job_key", job_key(candidate)), "status": status, "reason": reason, **fields}), flush=True)


def available_regions(settings, store, execute):
    regions = {}
    total, _ = store.usage()
    if execute and total >= settings["daily_limit"]:
        return regions
    for service, cfg in settings["services"].items():
        _, used = store.usage(service)
        if not execute or used < cfg.get("daily_limit", settings["daily_limit"]):
            regions[service] = cfg.get("region", SERVICES[service][1])
    return regions


def rows_for(settings, store, execute, series, limit):
    regions = available_regions(settings, store, execute)
    if not regions or limit < 1:
        return []
    media_types = settings.get("media_types", ["movie"])
    kinds = ["series"] if series else (["movie"] if "movie" in media_types else []) + (["episode"] if "tv" in media_types else [])
    states = ["pending", "unknown", "expanded"] if series else ["pending", "unknown", "ready"]
    # Filter before LIMIT/ranking: old popular-page jobs without rarity metadata
    # must not consume the entire rare-title check budget.
    store.db.create_function("catalogue_selected", 1, lambda raw: int(selection_matches(json.loads(raw), settings)), deterministic=True)
    return store.db.execute(
        """WITH eligible AS (SELECT * FROM jobs
        WHERE status IN (SELECT value FROM json_each(?)) AND next_check<=? AND catalogue_selected(candidate)=1
        AND json_extract(?, '$.' || service)=json_extract(candidate,'$.region')
        AND json(coalesce(json_extract(candidate,'$.origin_countries'),'[]'))=?
        AND coalesce(json_extract(candidate,'$.media_type'),'movie') IN (SELECT value FROM json_each(?))
        ), priorities AS (SELECT *,CASE WHEN ? AND status='ready' THEN 0 ELSE 1 END AS priority FROM eligible),
        ranked AS (SELECT *,row_number() OVER (PARTITION BY service ORDER BY priority,coalesce(checked,0),discovered,job_key) AS service_rank FROM priorities)
        SELECT * FROM ranked ORDER BY priority,service_rank,coalesce(checked,0),discovered,job_key LIMIT ?""",
        (
            json.dumps(states),
            time.time(),
            json.dumps(regions),
            json.dumps(sorted(settings.get("origin_countries", [])), separators=(",", ":")),
            json.dumps(kinds),
            execute,
            limit,
        ),
    ).fetchall()


def process_advanced(settings: dict, store: Store, execute: bool, metadata=None, slots=None, downloader=None, inventory=None, access_probe=None):
    from src.catalogue_access import record_native_access
    from src.catalogue_prime_probe import PrimeAccessProbe

    prime_probe = access_probe
    from src.catalogue_runner import download

    def account_access(candidate, key):
        if not settings.get("require_prime_inclusion") or candidate.get("service") != "amazon":
            return True
        nonlocal prime_probe
        try:
            if prime_probe is None:
                prime_probe = PrimeAccessProbe(settings)
            proof = prime_probe.check(candidate)
        except MetadataStopError:
            raise
        except (RunnerError, OSError, ValueError):
            proof = {"state": "unknown", "reason": "Automatic Prime account check could not verify this exact title/profile/region"}
        record_native_access(store, key, candidate, proof)
        if proof.get("state") == "included":
            if proof.get("canonical_item"):
                candidate["canonical_item"] = proof["canonical_item"]
            return True
        status = "filtered" if proof.get("state") == "paid" else "review"
        reason = proof["reason"]
        state = "rent_buy_or_addon" if proof.get("state") == "paid" else "unverified"
        store.update(key, status, reason, {"source_access": state, "account_access": proof})
        emit(candidate, status, reason)
        return False

    metadata, slots = metadata or MetadataProbe(settings), slots or SlotChecker(settings)
    downloader = downloader or download
    if execute and not available_regions(settings, store, True):
        print(json.dumps({"status": "paused", "reason": "Daily global/service start limits reached"}))
        return
    checked, launched = 0, 0
    metadata_failures, paused_services = {}, set()
    if "tv" in settings.get("media_types", []):
        parents = rows_for(settings, store, execute, True, min(settings.get("max_series_expansions_per_run", 2), settings["max_checks_per_run"]))
        for row in parents:
            candidate = json.loads(row["candidate"])
            if not account_access(candidate, row["job_key"]):
                continue
            if not selection_matches(candidate, settings):
                store.update(row["job_key"], "filtered", "Excluded by current catalogue year/title criteria")
                continue
            checked += 1
            try:
                if time.time() - row["discovered"] > settings["max_candidate_age_hours"] * 3600:
                    store.update(row["job_key"], "stale", "Series catalogue availability expired")
                    continue
                if not verify_original_language(settings, inventory, store, candidate):
                    store.update(row["job_key"], "filtered", "Original language does not match the selected catalogue languages")
                    emit(candidate, "filtered", "Original language does not match the selected catalogue languages")
                    continue
                listing = metadata.list(candidate)
                previous = store.episode_states(candidate["imdb"])
                terminal = {key for key, state in previous.items() if state in {"started", "succeeded", "failed", "uncertain"}}
                # Metadata size is independently capped at 4 MiB. Refresh existing
                # unstarted episodes without starving later, undiscovered ones.
                episodes = episodes_from_listing(candidate, listing, 50000, settings.get("include_specials", False), excluded=terminal)
                added = 0
                with store.db:
                    for episode in episodes:
                        key = job_key(episode)
                        if key not in previous:
                            if added >= settings.get("max_episodes_per_title", 30):
                                continue
                            added += 1
                        store.add(episode)
                store.defer_series(row["job_key"], added, settings.get("series_refresh_minutes", 60))
                emit(candidate, "expanded", f"Discovered {added} new episodes; completed/uncertain jobs not replayed")
            except PlaybackUnavailableError as exc:
                store.update(row["job_key"], "unavailable", str(exc))
                emit(candidate, "unavailable", str(exc))
            except RunnerError as exc:
                store.update(row["job_key"], "unknown", str(exc))
                emit(candidate, "unknown", str(exc))
                if isinstance(exc, MetadataStopError):
                    return
    remaining = max(0, settings["max_checks_per_run"] - checked)
    for row in rows_for(settings, store, execute, False, remaining):
        if execute and launched >= settings["max_downloads_per_run"]:
            break
        candidate, key = json.loads(row["candidate"]), row["job_key"]
        if not selection_matches(candidate, settings):
            store.update(key, "filtered", "Excluded by current catalogue year/title criteria")
            continue
        if time.time() - row["discovered"] > settings["max_candidate_age_hours"] * 3600:
            store.update(key, "stale", "Catalogue availability expired; no download permitted")
            continue
        if execute and candidate["service"] not in available_regions(settings, store, True):
            continue
        service = candidate["service"]
        if not account_access(candidate, key):
            continue
        if metadata_failures.get(service, 0) >= 2:
            if service not in paused_services:
                print(json.dumps({"status": "paused", "reason": f"{service}: repeated metadata failures; remaining titles deferred without more requests"}), flush=True)
                paused_services.add(service)
            continue
        presence = {}
        # In strict absence mode, stop at the FIRST selected tracker hit.
        # No later tracker calls or provider/manifest requests are then needed.
        if inventory is not None and settings["eligibility"] == "absent_all" and candidate.get("media_type", "movie") == "movie":
            presence = inventory.check_until_hit(candidate["imdb"])
            hit = next((alias for alias, state in presence.items() if state == "present"), None)
            if hit:
                reason = f"Exact title already exists on {hit}; stopped remaining tracker/provider requests"
                store.update(key, "blocked", reason, {"inventory": presence})
                emit(candidate, "blocked", reason)
                continue
            if set(presence) != set(settings["trackers"]) or any(state != "absent" for state in presence.values()):
                errors = getattr(inventory, "last_errors", {})
                detail = "; ".join(f"{alias}: {errors.get(alias, 'inventory incomplete')}" for alias, state in presence.items() if state == "unknown")
                reason = ("Selected tracker inventory is unknown/incomplete; no provider request or download permitted. " + detail)[:1600]
                store.update(key, "unknown", reason, {"inventory": presence, "errors": errors})
                emit(candidate, "unknown", reason)
                continue
        if settings.get("discovery_inventory_only") is True and not execute and presence:
            try:
                if not verify_original_language(settings, inventory, store, candidate):
                    store.update(key, "filtered", "Original language does not match selected languages")
                    continue
                identity = inventory._tmdb_identity(candidate["imdb"], "movie")

                def normalize(value):
                    return "".join(c for c in str(value).casefold() if c.isalnum())

                names = {normalize(identity.get("title", "")), normalize(identity.get("original_title", ""))}
                if normalize(candidate.get("title", "")) not in names or str(candidate.get("year")) != str(identity.get("release_date", ""))[:4]:
                    raise RunnerError("Catalogue title/year disagrees with exact IMDb identity; manual identity review required")
                store.update(
                    key,
                    "review",
                    "Verified tracker title gap; streaming entitlement/quality not checked. No download.",
                    {"inventory": presence, "identity_verified": True, "tmdb": identity["id"]},
                )
                emit(candidate, "review", "Tracker gap saved; streaming access unverified")
            except RunnerError as exc:
                store.update(key, "unknown", str(exc), {"identity_verified": False})
                emit(candidate, "unknown", str(exc))
            continue
        phase = "language"
        try:
            if not verify_original_language(settings, inventory, store, candidate):
                store.update(key, "filtered", "Original language does not match the selected catalogue languages")
                emit(candidate, "filtered", "Original language does not match the selected catalogue languages")
                continue
            phase = "metadata"
            profile = metadata.item_profile(candidate)
            metadata_failures[service] = 0
            phase = "tracker"
            evidence = slots.check(candidate, profile)
            allowed = eligible(evidence, settings["eligibility"], settings["trackers"])
            if not allowed:
                state = (
                    "blocked"
                    if settings["eligibility"] == "absent_all" and any(entry.get("existing_count", 0) > 0 and entry["state"] != "not_applicable" for entry in evidence.values())
                    else "unknown"
                    if any(entry["state"] == "unknown" for entry in evidence.values())
                    else "review"
                    if any(entry["state"] == "review" for entry in evidence.values())
                    else "blocked"
                )
                reason = "; ".join(f"{alias}: {entry.get('reason', entry['state'])}" for alias, entry in evidence.items())[:1600]
                store.update(key, state, reason, {"trackers": evidence, "profile": profile})
                emit(candidate, state, reason)
                continue
            command = cardinal_command(settings, candidate, profile)
            store.update(key, "ready", "Verified metadata and tracker evidence; GUI profile snapshot selected", {"trackers": evidence, "profile": profile})
            if not execute:
                emit(candidate, "ready", "No download: dry-run", service=candidate["service"])
                continue
            if shutil.disk_usage(Path(settings["disk_path"]).expanduser()).free < settings["min_free_gib"] * 1024**3:
                print(json.dumps({"status": "paused", "reason": "Minimum free space reached"}))
                break
            # Always a fresh slot check in this invocation; never trust stored ready evidence.
            if not store.reserve(key, candidate["service"], settings["daily_limit"], settings["services"][candidate["service"]].get("daily_limit", settings["daily_limit"])):
                continue
            launched += 1
            outcome = downloader(command, settings["timeout_seconds"])
            store.update(key, outcome, "Cardinal exit status only; payload not independently verified", {"trackers": evidence, "profile": profile})
            emit(candidate, outcome)
            if outcome == "uncertain":
                break
        except PlaybackUnavailableError as exc:
            # A definitive per-title rejection is not an outage. Continue the
            # bounded batch, rather than starving later playable candidates.
            metadata_failures[service] = 0
            store.update(key, "unavailable", str(exc), {"inventory": presence})
            emit(candidate, "unavailable", str(exc))
        except RunnerError as exc:
            if phase == "metadata":
                metadata_failures[service] = metadata_failures.get(service, 0) + 1
            store.update(key, "unknown", str(exc), {"inventory": presence})
            emit(candidate, "unknown", str(exc))
            if isinstance(exc, MetadataStopError):
                break

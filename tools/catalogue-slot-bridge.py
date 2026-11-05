#!/usr/bin/env python3
"""Reuse the installed UA tracker adapters/rules in an isolated subprocess.

JSON input/output only. Never uploads, prompts, touches payloads, or exports keys.
--evaluate-only forbids network access and evaluates supplied inventory fixtures.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import importlib.util
import json
import logging
import os
import re
import runpy
import socket
import sys
import types
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from urllib.parse import urlsplit

ALIASES = {"HDB": "HDBITS", "PTP": "PASSTHEPOPCORN", "ATH": "AITHER", "DT": "DESITORRENTS"}
INDIAN = frozenset({"hi", "ta", "te", "kn", "ml", "bn", "mr", "gu", "pa", "or", "as", "ur", "ne", "sa", "sd", "ks", "mai", "kok", "doi", "sat", "mni", "brx"})


def languages(values):
    if values is None:
        return None
    import langcodes

    return frozenset(langcodes.Language.get(value).language for value in values)


def provider(name):
    match = re.search(r"(?<![A-Za-z0-9])(AMZN|AMAZON|NF|NETFLIX|ATVP|ATV)(?![A-Za-z0-9])", name, re.I)
    return {"AMAZON": "AMZN", "NETFLIX": "NF", "ATV": "ATVP"}.get(match[1].upper(), match[1].upper()) if match else None


async def evaluate(request, ua, offline):
    import httpx

    from src.dupe_checking import DupeChecker
    from src.meta import Meta
    from src.slot_rules.models import Verdict
    from src.slot_rules.profile import WEBDL, ReleaseProfile, profile_from_entry
    from src.slot_rules.registry import SLOT_RULES
    from src.trackers.GAZELLE.passthepopcorn import PassThePopcorn
    from src.trackers.hdbits import _hdb_dupe_entry
    from src.trackers.UNIT3D.aither import Aither
    from src.trackers.UNIT3D.torrentdesi import DesiTorrents

    candidate, plan = request["candidate"], request["profile"]
    imdb = candidate["imdb"]
    if not re.fullmatch(r"tt\d{7,10}", imdb) or plan.get("codec") not in {"H264", "H265", "AV1"} or not re.fullmatch(r"\d{3,4}p", plan.get("resolution", "")):
        raise ValueError("Invalid identity/profile")
    aliases = request["trackers"]
    if not aliases or any(alias not in ALIASES for alias in aliases):
        raise ValueError("Invalid trackers")
    episode = candidate.get("media_type") == "episode"
    category = "TV" if episode else "MOVIE"
    tmdb = candidate.get("tmdb_id")
    if not offline and any(alias in aliases for alias in ("ATH", "DT")) and not tmdb:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    f"https://api.themoviedb.org/3/find/{imdb}", params={"external_source": "imdb_id", "api_key": ua.get("DEFAULT", {}).get("tmdb_api", "")}
                )
            response.raise_for_status()
            data = response.json().get("tv_results" if episode else "movie_results")
            if not isinstance(data, list) or len(data) != 1 or type(data[0].get("id")) is not int or data[0]["id"] <= 0:
                raise ValueError("Ambiguous TMDB identity")
            tmdb = data[0]["id"]
        except Exception:
            tmdb = None
    audio, subtitles = languages(plan.get("audio_languages")), languages(plan.get("subtitle_languages"))
    episode_tag = f".S{candidate['season']:02}E{candidate['episode']:02}" if episode else ""
    name = f"{candidate['title']}.{candidate.get('year') or ''}{episode_tag}.{plan['resolution']}.{plan['provider']}.WEB-DL.{plan['codec']}"
    meta = Meta(
        {
            "category": category,
            "type": "WEBDL",
            "source": "WEB",
            "service": plan["provider"],
            "resolution": plan["resolution"],
            "name": name,
            "title": candidate["title"],
            "year": str(candidate.get("year") or ""),
            "imdb": imdb[2:],
            "imdb_id": int(imdb[2:]),
            "tmdb": tmdb,
            "tmdb_id": tmdb,
            "video_width": plan.get("video_width") or 0,
            "video_height": plan.get("video_height") or 0,
            "container": plan.get("container", "mkv"),
            "path": name + "." + plan.get("container", "mkv"),
            "unattended": True,
            "season": f"S{candidate.get('season', 0):02}" if episode else "",
            "episode": f"E{candidate.get('episode', 0):02}" if episode else "",
            "season_int": candidate.get("season", 0),
            "episode_int": candidate.get("episode", 0),
            "tv_pack": False,
            "imdb_info": {"type": "tv series" if episode else "movie", "genres": []},
        }
    )
    planned = ReleaseProfile(
        name=name,
        kind=WEBDL,
        resolution=plan["resolution"],
        codec=plan["codec"],
        hdr=frozenset(plan["hdr"]),
        hybrid=plan.get("hybrid") is True,
        provider=plan["provider"],
        audio_languages=audio,
        subtitle_languages=subtitles,
    )
    result = {}
    for alias in aliases:
        if request.get("stop_on_hit") is True and any(value.get("existing_count", 0) > 0 and value.get("state") != "not_applicable" for value in result.values()):
            result[alias] = {"state": "unknown", "reason": "Not queried: an earlier selected tracker already confirmed a hit"}
            continue
        tracker = ALIASES[alias]
        if not offline and alias in {"ATH", "DT"} and not tmdb:
            result[alias] = {"state": "unknown", "reason": "Exact TMDB identity could not be established"}
            continue
        if alias == "DT" and audio is None:
            result[alias] = {"state": "review", "reason": "Selected audio languages are unknown; DesiTorrents eligibility is unverified"}
            continue
        if alias == "DT" and audio is not None and not audio & INDIAN:
            result[alias] = {"state": "not_applicable", "reason": "No selected Indian-language audio for DesiTorrents"}
            continue
        try:
            if offline:
                entries = request.get("inventories", {}).get(alias)
                if not isinstance(entries, list):
                    raise ValueError("Incomplete fixture inventory")
            elif alias == "HDB":
                config = ua["TRACKERS"][tracker]
                async with httpx.AsyncClient(timeout=30) as client:
                    response = await client.post(
                        "https://hdbits.org/api/torrents", json={"username": config["username"], "passkey": config["passkey"], "imdb": {"id": imdb[2:]}, "limit": 100}
                    )
                response.raise_for_status()
                data = response.json()
                rows = data.get("data")
                if (
                    data.get("error")
                    or data.get("Error")
                    or data.get("errors")
                    or data.get("success") is False
                    or data.get("status") not in {None, 0}
                    or not isinstance(rows, list)
                    or len(rows) >= 100
                    or any(not isinstance(row, dict) for row in rows)
                ):
                    raise ValueError("HDB inventory incomplete")
                entries = [_hdb_dupe_entry(row, "https://hdbits.org", "") for row in rows]
            elif alias == "PTP":
                adapter = PassThePopcorn(ua)
                group = await adapter.get_group_by_imdb(imdb[2:], strict=True, allow_prompt=False)
                entries = await adapter.search_existing(group, meta) if group else []
            else:
                adapter = (Aither if alias == "ATH" else DesiTorrents)(ua)
                adapter.search_whole_title = True
                original_urls = adapter.get_search_urls

                async def whole_title_urls(metadata, parameters, original=original_urls, current=adapter):
                    urls = await original(metadata, parameters)
                    category_id = (await current.get_category_id(metadata))["category_id"]
                    return [(url, [(key, value) for key, value in params if key != "name"] + [("categories[]", category_id)], pending) for url, params, pending in urls]

                adapter.get_search_urls = whole_title_urls
                await adapter.search_existing(meta)
                entries = meta.get(f"{tracker}_title_releases")
                if not isinstance(entries, list) or meta.get(f"{tracker}_search_failed") or meta.get(f"{tracker}_search_incomplete"):
                    raise ValueError("Incomplete title inventory")
            if alias == "PTP" and episode:
                result[alias] = {
                    "state": "block" if entries else "not_applicable",
                    "reason": "Exact IMDb group already has PTP releases; no episodic slot assumed"
                    if entries
                    else "PTP inventory empty; general episode uploads are not eligible",
                }
                continue
            if episode and entries:
                relevant = []
                for entry in entries:
                    entry_name = str(entry.get("name") or "")
                    normalized = await DupeChecker.normalize_filename(entry_name)
                    matches, pack = await DupeChecker.is_season_episode_match(normalized, meta.season, meta.episode)
                    if matches:
                        if pack:
                            raise ValueError("A season pack may cover the episode")
                        relevant.append(entry)
                    elif re.search(r"\bcomplete\b", entry_name, re.I) or not re.search(r"[sS]\d{1,3}|\d{1,3}[xX]\d{1,3}", entry_name):
                        raise ValueError("Episode coverage is ambiguous")
                entries = relevant
            if not entries:
                result[alias] = {"state": "absent", "reason": "Complete exact-title/episode inventory is empty"}
                continue
            if alias == "DT":
                result[alias] = {"state": "block", "reason": "Title/episode exists; no verified DesiTorrents free-slot rule"}
                continue
            if ua.get("DEFAULT", {}).get("slot_rules", True) is False:
                result[alias] = {"state": "review", "reason": "UA slot rules are disabled; only confirmed absence is eligible"}
                continue
            profiles = [profile_from_entry(entry, provider=provider(str(entry.get("name") or ""))) for entry in entries]
            rules = SLOT_RULES[tracker](meta)
            decision = rules.evaluate(planned, profiles)
            allowed = decision.verdict is Verdict.ALLOW and not decision.requires_evidence and not decision.trump_recommended and not decision.constraint_violation
            result[alias] = {
                "state": "allow" if allowed else "block" if decision.verdict is Verdict.BLOCK else "review",
                "reason": decision.reason[:800],
                "slot": decision.slot[:200],
                "requires_evidence": decision.requires_evidence,
                "trump": decision.trump_recommended,
                "requirements": [str(value)[:300] for value in decision.requirements[:10]],
                "existing_count": len(entries),
            }
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            detail = str(exc) if type(exc).__name__ == "RateLimitError" else f"HTTP {status}" if type(status) is int else type(exc).__name__
            result[alias] = {"state": "unknown", "reason": f"Tracker inventory/rules incomplete ({detail}); no vacant slot assumed"}
    return {"schema": 1, "trackers": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ua-root", type=Path, required=True)
    parser.add_argument("--ua-config", type=Path, required=True)
    parser.add_argument("--evaluate-only", action="store_true")
    parser.add_argument("--rate-state", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.ua_root.resolve()))
    os.environ["UA_DATA_DIR"] = str(args.ua_config.parent.parent)
    raw = sys.stdin.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise SystemExit(2)
    try:
        request = json.loads(raw)
        with Path(os.devnull).open("w") as quiet, redirect_stdout(quiet), redirect_stderr(quiet):
            logging.disable(logging.CRITICAL)
            if args.evaluate_only:

                def forbidden(*_args, **_kwargs):
                    raise RuntimeError("Network forbidden in fixture evaluation")

                socket.socket.connect = forbidden
                socket.create_connection = forbidden
            else:
                import httpx

                if not args.rate_state:
                    raise ValueError("A private shared API pacing state is required")
                spec = importlib.util.spec_from_file_location("catalogue_rate_bridge", Path(__file__).resolve().parents[1] / "src/catalogue_rate.py")
                rate_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(rate_module)
                pacer = rate_module.APIPacer(args.rate_state, request.get("rate_interval", 10), request.get("rate_daily_limit", 200))
                original_client = httpx.AsyncClient
                locks = {}

                class PacedClient(original_client):
                    def __init__(self, *values, **kwargs):
                        kwargs["follow_redirects"] = False
                        super().__init__(*values, **kwargs)

                    async def request(self, method, url, **kwargs):
                        parsed = urlsplit(str(url))
                        host = parsed.hostname
                        if (
                            parsed.scheme != "https"
                            or host not in {"hdbits.org", "passthepopcorn.me", "aither.cc", "torrent.desi", "api.themoviedb.org"}
                            or parsed.username
                            or parsed.password
                        ):
                            raise ValueError("Tracker adapter attempted an unapproved API origin")
                        kwargs["follow_redirects"] = False
                        lock = locks.setdefault(host, asyncio.Lock())
                        async with lock:
                            for hop in range(2):
                                await asyncio.to_thread(pacer.acquire, host)
                                response = await super().request(method, url, **kwargs)
                                await asyncio.to_thread(pacer.record_response, host, response)
                                target = (
                                    rate_module.ptp_api_redirect(response.request.url, response.headers.get("location"))
                                    if method.upper() == "GET" and response.status_code in {301, 302, 303, 307, 308}
                                    else None
                                )
                                if hop == 0 and target:
                                    url = target
                                    kwargs.pop("params", None)
                                    continue
                                return response
                            raise ValueError("API redirect limit exceeded")

                httpx.AsyncClient = PacedClient
            ua = runpy.run_path(str(args.ua_config))["config"] if not args.evaluate_only else runpy.run_path(str(args.ua_root / "data/example_config.py"))["config"]
            # UA helpers import data.config. Install the same in-memory config
            # instead of reading a legacy checkout config or exporting keys.
            package = importlib.import_module("data")
            config_module = types.ModuleType("data.config")
            config_module.config = ua
            sys.modules["data.config"] = config_module
            package.config = config_module
            result = asyncio.run(evaluate(request, ua, args.evaluate_only))
        print(json.dumps(result))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "schema": 1,
                    "error": "Metadata/UA adapter validation failed; no download permitted",
                    "error_type": type(exc).__name__,
                    "error_module": getattr(exc, "name", None),
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

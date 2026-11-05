"""API-only catalogue discovery and conservative unattended CardinalDL queue.

No uploads, scraping, profile changes, or automatic replay of uncertain downloads.
Run via tools/catalogue-runner.py. See docs/catalogue-runner.md.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import fcntl
import json
import os
import re
import runpy
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx

from src.catalogue_store import Store

if __name__ == "__main__":
    sys.modules.setdefault("src.catalogue_runner", sys.modules[__name__])


class RunnerError(Exception):
    """Safe-to-display error; never include response bodies or credential URLs."""


SERVICES = {
    "amazon": ("amp", "GB"),
    "netflix": ("nfx", "US"),
    "appletv": ("atp", "US"),
}
TRACKERS = {"HDB": "HDBITS", "PTP": "PASSTHEPOPCORN", "ATH": "AITHER", "DT": "DESITORRENTS"}
QUERY = """
query Catalogue($country: Country!, $filter: TitleFilter, $packages: [String!], $after: String, $offset: Int) {
  popularTitles(country: $country, filter: $filter, first: 40, after: $after, offset: $offset) {
    pageInfo { endCursor hasNextPage }
    edges { node { id objectType
      content(country: $country, language: en) {
        ... on MovieContent { title originalReleaseYear runtime isReleased scoring { imdbVotes } externalIds { imdbId } }
        ... on ShowContent { title originalReleaseYear runtime isReleased scoring { imdbVotes } externalIds { imdbId } }
      }
      offers(country: $country, platform: WEB, filter: {packages: $packages}) {
        monetizationType standardWebURL package { shortName }
      }
    } }
  }
}
"""


def utc_day():
    return datetime.now(UTC).date().isoformat()


VIDEO_MODES = {"saved", "sdr", "hdr10", "hdr10+", "dv", "dv-hdr10", "dv-hdr10+", "hlg"}
VIDEO_MODE_HDR = {"sdr": set(), "hdr10": {"HDR10"}, "hdr10+": {"HDR10+"}, "dv": {"DV"}, "dv-hdr10": {"DV", "HDR10"}, "dv-hdr10+": {"DV", "HDR10+"}, "hlg": {"HLG"}}


def video_mode_arguments(settings: dict) -> list[str]:
    mode = settings.get("video_mode", "saved")
    if mode not in VIDEO_MODES:
        raise RunnerError("Unsupported catalogue video mode")
    if mode == "saved":
        return []
    return ["--vq", f"@@{mode}", f"--hybrid={'true' if mode in {'dv-hdr10', 'dv-hdr10+'} else 'false'}", "--fallback=false"]


def provider_id(service: str, url: str) -> str | None:
    """Only parse provider-owned URLs. Never fetch/execute catalogue URLs."""
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return None
    if service == "netflix" and host in {"netflix.com", "www.netflix.com"}:
        match = re.search(r"/(?:title|watch)/(\d+)(?:/|$)", parsed.path)
        return match[1] if match else None
    if service == "appletv" and host == "tv.apple.com":
        match = re.search(r"/(umc\.cmc\.[a-zA-Z0-9]+)(?:/|$)", parsed.path)
        return match[1] if match else None
    if service == "amazon" and host in {
        "amazon.com",
        "www.amazon.com",
        "amazon.co.uk",
        "www.amazon.co.uk",
        "watch.amazon.com",
        "watch.amazon.co.uk",
        "primevideo.com",
        "www.primevideo.com",
    }:
        match = re.search(r"/(?:detail|dp|gp/video/detail)/([A-Z0-9]{10})(?:/|$)", parsed.path)
        if match:
            return match[1]
        gti = parse_qs(parsed.query).get("gti", [""])[0]
        if re.fullmatch(r"amzn1\.dv\.gti\.[a-fA-F0-9-]{36}", gti):
            return gti
    return None


def load_settings(path: Path) -> tuple[dict, dict]:
    settings = json.loads(path.read_text())
    if not isinstance(settings, dict):
        raise RunnerError("Runner configuration must be an object")
    settings.setdefault("eligibility", "absent_all")
    if settings["eligibility"] not in {"absent_all", "missing_any", "missing_or_free_slot"}:
        raise RunnerError("eligibility must be absent_all, missing_any, or missing_or_free_slot")
    settings.setdefault("media_types", ["movie"])
    media_types = settings["media_types"]
    if not isinstance(media_types, list) or not media_types or any(value not in {"movie", "tv"} for value in media_types) or len(set(media_types)) != len(media_types):
        raise RunnerError("media_types must select movie and/or tv")
    for flag in ("verify_cardinal", "include_specials", "require_prime_inclusion", "discovery_only", "discovery_inventory_only"):
        if type(settings.get(flag, False)) is not bool:
            raise RunnerError(f"{flag} must be a boolean")
    trackers = settings.get("trackers", list(TRACKERS))
    if not isinstance(trackers, list) or not trackers or len(set(trackers)) != len(trackers) or any(t not in TRACKERS for t in trackers):
        raise RunnerError("trackers must be a non-empty unique list of HDB, PTP, ATH, DT")
    services = settings.get("services", {})
    if not isinstance(services, dict) or not services or any(s not in SERVICES for s in services):
        raise RunnerError("Configure at least one of amazon, netflix, appletv")
    for service, cfg in services.items():
        if not isinstance(cfg, dict):
            raise RunnerError("Each service configuration must be an object")
        if not re.fullmatch(r"[A-Z]{2}", cfg.get("region", SERVICES[service][1])):
            raise RunnerError("Service regions must be two-letter uppercase codes (UK is GB)")
    countries = settings.get("origin_countries", [])
    if not isinstance(countries, list) or any(not isinstance(c, str) or not re.fullmatch(r"[A-Z]{2}", c) for c in countries):
        raise RunnerError("origin_countries must be a list of two-letter uppercase codes")
    if not isinstance(settings.get("video_mode", "saved"), str) or settings.get("video_mode", "saved") not in VIDEO_MODES:
        raise RunnerError("video_mode must be saved, sdr, hdr10, hdr10+, dv, dv-hdr10, dv-hdr10+, or hlg")
    languages = settings.get("original_languages", [])
    if (
        not isinstance(languages, list)
        or len(languages) > 20
        or any(not isinstance(code, str) or not re.fullmatch(r"[a-z]{2}", code) for code in languages)
        or len(set(languages)) != len(languages)
    ):
        raise RunnerError("original_languages must be unique lowercase two-letter language codes (for example ta, te, hi); at most 20")
    for name, default, minimum in [
        ("daily_limit", 5, 0),
        ("pages_per_service", 1, 1),
        ("max_downloads_per_run", 2, 0),
        ("max_checks_per_run", 20, 1),
        ("timeout_seconds", 14400, 1),
        ("max_candidate_age_hours", 24, 1),
        ("min_free_gib", 50, 0),
        ("max_episodes_per_title", 30, 1),
        ("max_series_expansions_per_run", 2, 1),
        ("metadata_timeout_seconds", 180, 1),
        ("slot_timeout_seconds", 180, 1),
        ("series_refresh_minutes", 60, 5),
        ("tracker_request_interval_seconds", 10, 2),
        ("tracker_daily_api_limit", 200, 1),
        ("min_release_year", 0, 0),
        ("max_release_year", 0, 0),
        ("discovery_start_offset", 0, 0),
        ("min_imdb_votes", 0, 0),
        ("max_imdb_votes", 0, 0),
        ("min_runtime_minutes", 0, 0),
        ("max_runtime_minutes", 0, 0),
    ]:
        value = settings.get(name, default)
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise RunnerError(f"{name} must be an integer >= {minimum}")
        settings[name] = value
    current_year = datetime.now(UTC).year
    minimum, maximum = settings["min_release_year"], settings["max_release_year"] or current_year
    if (minimum and not 1800 <= minimum <= current_year) or not 1800 <= maximum <= current_year or minimum > maximum:
        raise RunnerError("Release year bounds must be valid, ordered, and not in the future; zero means unrestricted/current year")
    settings.setdefault("selection_order", "recent")
    if settings["selection_order"] not in {"recent", "oldest", "obscure", "catalogue"}:
        raise RunnerError("selection_order must be recent, oldest, obscure or catalogue")
    for lower, upper, ceiling in (("min_imdb_votes", "max_imdb_votes", 100000000), ("min_runtime_minutes", "max_runtime_minutes", 1440)):
        if settings[lower] > ceiling or settings[upper] > ceiling or (settings[upper] and settings[lower] > settings[upper]):
            raise RunnerError(f"Invalid {lower}/{upper} range")
    if settings["discovery_start_offset"] > 10000:
        raise RunnerError("discovery_start_offset must be between zero and 10000")
    settings.setdefault("exclude_title_keywords", [])
    keywords = settings["exclude_title_keywords"]
    if not isinstance(keywords, list) or len(keywords) > 25 or any(not isinstance(value, str) or not value.strip() or len(value) > 100 for value in keywords):
        raise RunnerError("exclude_title_keywords must contain at most 25 non-empty short phrases")
    for cfg in services.values():
        limit = cfg.get("daily_limit", settings["daily_limit"])
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise RunnerError("Service daily_limit must be a non-negative integer")
    if type(settings.get("allow_downloads", False)) is not bool:
        raise RunnerError("allow_downloads must be a boolean")
    docker = settings.get("cardinal_docker")
    if docker is not None:
        if not isinstance(docker, dict) or not isinstance(docker.get("container"), str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", docker["container"]):
            raise RunnerError("cardinal_docker requires an exact container name")
        for field in ("user", "workdir", "cli"):
            if field in docker and (not isinstance(docker[field], str) or not docker[field] or docker[field].startswith("-") or "\x00" in docker[field]):
                raise RunnerError("Invalid Docker CLI configuration")
    advanced = settings.get("verify_cardinal") or "tv" in media_types or settings["eligibility"] != "absent_all" or settings.get("video_mode", "saved") != "saved"
    if advanced:
        for key in ("ua_root", "cardinal_exchange_host", "cardinal_exchange_container"):
            if not isinstance(settings.get(key), str) or not settings[key].startswith("/"):
                raise RunnerError(f"Configure the dedicated {key} path before advanced discovery")
        if not docker:
            raise RunnerError("Advanced metadata currently requires the validated Cardinal Docker adapter")
        if not (Path(settings["ua_root"]) / "src/slot_rules/registry.py").is_file():
            raise RunnerError("Installed UA slot-rule registry not found")
    # This is the existing trusted UA Python config, not an untrusted remote file.
    ua_path = Path(settings["ua_config"]).expanduser()
    ua = runpy.run_path(str(ua_path)).get("config")
    if not isinstance(ua, dict):
        raise RunnerError("UA configuration does not export config")
    for alias in trackers:
        cfg = ua.get("TRACKERS", {}).get(TRACKERS[alias], {})
        required = {"HDB": ("username", "passkey"), "PTP": ("ApiUser", "api_key"), "ATH": ("api_key",), "DT": ("api_key",)}[alias]
        if any(not isinstance(cfg.get(k), str) or not cfg[k].strip() for k in required):
            raise RunnerError(f"Missing existing UA API credentials for {alias}")
    settings["trackers"] = trackers
    return settings, ua


class API:
    """Fixed API origins, no redirects, paced calls; API failures are never absence."""

    def __init__(self, client: httpx.Client, interval: float = 2, pacer=None):
        self.client = client
        self.interval = interval
        self.pacer = pacer
        self.last: dict[str, float] = {}

    def request(self, method: str, url: str, **kwargs):
        from src.catalogue_rate import RateLimitError, ptp_api_redirect

        for hop in range(2):
            host = urlsplit(url).netloc
            if self.pacer:
                try:
                    self.pacer.acquire(host)
                except RateLimitError as exc:
                    raise RunnerError(str(exc)) from None
            time.sleep(max(0, self.interval - (time.monotonic() - self.last.get(host, 0))))
            self.last[host] = time.monotonic()
            try:
                response = self.client.request(method, url, **kwargs)
                if self.pacer and self.pacer.record_response(host, response) == 429:
                    raise RunnerError("API rate limit response; shared cooldown recorded")
                target = (
                    ptp_api_redirect(response.request.url, response.headers.get("location"))
                    if method.upper() == "GET" and response.status_code in {301, 302, 303, 307, 308}
                    else None
                )
                if hop == 0 and target:
                    url = target
                    kwargs.pop("params", None)
                    continue
                if response.status_code != 200:
                    raise RunnerError(f"API HTTP {response.status_code}; result unknown")
                data = response.json()
            except (httpx.HTTPError, ValueError):
                raise RunnerError("API transport/JSON failure; result unknown") from None
            if not isinstance(data, dict) or data.get("errors") or data.get("error") or data.get("Error") or data.get("success") is False:
                raise RunnerError("API rejected request or returned an invalid object")
            return data
        raise RunnerError("API redirect limit reached; occupancy unknown")


def selection_matches(candidate: dict, settings: dict) -> bool:
    year, title = candidate.get("year"), candidate.get("title")
    minimum = settings.get("min_release_year", 0) or 1800
    maximum = settings.get("max_release_year", 0) or datetime.now(UTC).year
    for field, lower, upper in (("imdb_votes", "min_imdb_votes", "max_imdb_votes"), ("runtime_minutes", "min_runtime_minutes", "max_runtime_minutes")):
        low, high, value = settings.get(lower, 0), settings.get(upper, 0), candidate.get(field)
        if (low or high) and (type(value) is not int or value < low or (high and value > high)):
            return False
    return (
        candidate.get("is_released") is not False
        and (not settings.get("original_languages") or candidate.get("original_language") is None or candidate.get("original_language") in settings["original_languages"])
        and type(year) is int
        and minimum <= year <= maximum
        and isinstance(title, str)
        and bool(title.strip())
        and not any(word.casefold() in title.casefold() for word in settings.get("exclude_title_keywords", []))
    )


def catalogue_offset(cursor: str | None, initial=0) -> int:
    """JustWatch cursors encode absolute offsets; `after` alone is not reliable."""
    if cursor is None:
        return initial
    try:
        if not isinstance(cursor, str) or len(cursor) > 64:
            raise ValueError
        decoded = cursor if cursor.isdigit() else base64.b64decode(cursor + "=" * (-len(cursor) % 4), validate=True).decode("ascii")
        if not re.fullmatch(r"[0-9]{1,7}", decoded):
            raise ValueError
        offset = int(decoded)
        if offset > 1000000:
            raise ValueError
        return offset
    except (ValueError, binascii.Error):
        raise RunnerError("Catalogue cursor format changed; discovery stopped without guessing a page") from None


class Catalogue:
    def __init__(self, api: API):
        self.api = api

    def page(self, service: str, region: str, countries: list[str], cursor: str | None, media_types=("movie",), criteria=None):
        criteria = criteria or {}
        package = SERVICES[service][0]
        object_types = [kind for kind, name in (("MOVIE", "movie"), ("SHOW", "tv")) if name in media_types]
        filters = {
            "packages": [package],
            "objectTypes": object_types,
            "monetizationTypes": ["FLATRATE"],
            "releaseYear": {"min": criteria.get("min_release_year", 0) or 1800, "max": criteria.get("max_release_year", 0) or datetime.now(UTC).year},
        }
        if criteria.get("min_imdb_votes", 0) or criteria.get("max_imdb_votes", 0):
            filters["imdbVotes"] = {"min": criteria.get("min_imdb_votes", 0), "max": criteria.get("max_imdb_votes", 0) or 100000000}
        if countries:
            filters["productionCountries"] = countries
        data = self.api.request(
            "POST",
            "https://apis.justwatch.com/graphql",
            json={
                "query": QUERY,
                "variables": {
                    "country": region,
                    "filter": filters,
                    "packages": [package],
                    "after": cursor,
                    "offset": catalogue_offset(cursor, criteria.get("discovery_start_offset", 0)),
                },
            },
        )
        try:
            page = data["data"]["popularTitles"]
            edges, info = page["edges"], page["pageInfo"]
            if not isinstance(edges, list) or type(info["hasNextPage"]) is not bool:
                raise ValueError
            next_cursor = info["endCursor"] if info["hasNextPage"] else None
            if info["hasNextPage"] and (not isinstance(next_cursor, str) or not next_cursor or next_cursor == cursor):
                raise ValueError
            candidates = []
            for edge in edges:
                node = edge["node"]
                content = node["content"]
                external = content.get("externalIds") or {}
                imdb = external.get("imdbId")
                if node["objectType"] not in object_types or not isinstance(imdb, str) or not re.fullmatch(r"tt\d{7,10}", imdb):
                    continue
                scoring = content.get("scoring") or {}
                if not isinstance(scoring, dict):
                    raise ValueError
                details = {
                    "year": content.get("originalReleaseYear"),
                    "title": content.get("title"),
                    "imdb_votes": scoring.get("imdbVotes"),
                    "runtime_minutes": content.get("runtime"),
                    "is_released": content.get("isReleased"),
                }
                if not selection_matches(details, criteria):
                    continue
                ids = set()
                for offer in node["offers"]:
                    if offer["monetizationType"] == "FLATRATE" and offer["package"]["shortName"] == package:
                        item = provider_id(service, offer.get("standardWebURL") or "")
                        if item:
                            ids.add(item)
                # Multiple provider IDs are ambiguous; never guess which edition to download.
                if len(ids) != 1:
                    continue
                candidates.append(
                    {
                        "imdb": imdb,
                        "service": service,
                        "region": region,
                        "item": ids.pop(),
                        "title": content["title"],
                        **details,
                        "catalogue_offer": {"package": package, "monetization": "FLATRATE", "region": region, "checked": time.time(), "account_entitlement_verified": False},
                        "origin_countries": sorted(countries),
                        "media_type": "series" if node["objectType"] == "SHOW" else "movie",
                    }
                )
            order = criteria.get("selection_order", "recent")
            if order == "recent":
                candidates.sort(key=lambda value: (-value["year"], value["title"].casefold(), value["imdb"]))
            elif order == "oldest":
                candidates.sort(key=lambda value: (value["year"], value["title"].casefold(), value["imdb"]))
            elif order == "obscure":
                candidates.sort(key=lambda value: (value["imdb_votes"] if type(value["imdb_votes"]) is int else 2**63, value["year"], value["imdb"]))
            return candidates, next_cursor
        except (KeyError, TypeError, ValueError):
            raise RunnerError("Catalogue schema changed or page incomplete; cursor was not advanced") from None


class Trackers:
    def __init__(self, api: API, ua: dict, enabled: list[str]):
        self.api, self.ua, self.enabled = api, ua, enabled
        self._identity_cache = {}

    def _tmdb_identity(self, imdb: str, kind: str) -> dict:
        if (imdb, kind) in self._identity_cache:
            return self._identity_cache[(imdb, kind)]
        key = self.ua.get("DEFAULT", {}).get("tmdb_api", "")
        if not key:
            raise RunnerError("UA TMDB API key is required for Unit3D title matching")
        data = self.api.request("GET", f"https://api.themoviedb.org/3/find/{imdb}", params={"api_key": key, "external_source": "imdb_id"})
        rows = data.get("movie_results" if kind == "movie" else "tv_results")
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict) or type(rows[0].get("id")) is not int or rows[0]["id"] <= 0:
            raise RunnerError(f"IMDb to TMDB {kind} identity is ambiguous or missing")
        self._identity_cache[(imdb, kind)] = rows[0]
        return rows[0]

    def tmdb_movie(self, imdb: str) -> int:
        return self._tmdb_identity(imdb, "movie")["id"]

    def original_language(self, imdb: str, media_type="movie") -> str:
        language = self._tmdb_identity(imdb, "movie" if media_type == "movie" else "tv").get("original_language")
        if not isinstance(language, str) or not re.fullmatch(r"[a-z]{2}", language):
            raise RunnerError("Exact IMDb identity has no verified original language; no provider request or download permitted")
        return language

    def absent(self, alias: str, imdb: str, tmdb: int | None) -> bool:
        cfg = self.ua["TRACKERS"][TRACKERS[alias]]
        if alias == "HDB":
            data = self.api.request(
                "POST",
                "https://hdbits.org/api/torrents",
                json={
                    "username": cfg["username"],
                    "passkey": cfg["passkey"],
                    "imdb": {"id": imdb[2:]},
                },
            )
            rows = data.get("data")
            if data.get("status") not in (None, 0) or not isinstance(rows, list):
                raise RunnerError("HDB inventory invalid; occupancy unknown")
            return not rows
        if alias == "PTP":
            data = self.api.request(
                "GET", "https://passthepopcorn.me/torrents.php", params={"imdb": imdb[2:], "json": "noredirect"}, headers={"ApiUser": cfg["ApiUser"], "ApiKey": cfg["api_key"]}
            )
            if data.get("Page") == "Details" and str(data.get("GroupId", "")).isdigit():
                return False
            if "TotalResults" in data:
                total = data["TotalResults"]
                if isinstance(total, bool) or not str(total).isdigit():
                    raise RunnerError("PTP inventory count invalid")
                if int(total) > 0:
                    return False
                if data.get("Movies") == []:
                    return True
            if data.get("Page") == "Browse" and data.get("Movies") == [] and "TotalResults" not in data:
                return True
            raise RunnerError("PTP response did not establish title occupancy")
        if not tmdb:
            raise RunnerError("Unit3D requires an exact TMDB movie ID")
        url = {"ATH": "https://aither.cc/api/torrents/filter", "DT": "https://torrent.desi/api/v1/torrents/filter"}[alias]
        data = self.api.request(
            "GET", url, params={"tmdbId": tmdb, "categories[]": 1, "perPage": 100}, headers={"authorization": f"Bearer {cfg['api_key']}", "accept": "application/json"}
        )
        rows = data.get("data")
        if not isinstance(rows, list):
            raise RunnerError("Unit3D inventory invalid")
        if rows:
            return False
        # An empty page is not proof of absence if pagination/count metadata disagrees.
        links = data.get("links")
        if not isinstance(links, dict) or "next" not in links or links["next"] is not None:
            raise RunnerError("Unit3D empty page has unknown pagination")
        metadata = data.get("meta", {})
        if not isinstance(metadata, dict):
            raise RunnerError("Unit3D pagination metadata invalid")
        total = metadata.get("total", 0)
        if isinstance(total, bool) or str(total) != "0":
            raise RunnerError("Unit3D empty page disagrees with inventory count")
        return True

    def check_until_hit(self, imdb: str) -> dict[str, str]:
        """Strict movie absence: a hit ends the lookup; unknown never means absent."""
        evidence, tmdb, mapping_attempted = {}, None, False
        self.last_errors = {}
        for alias in self.enabled:
            try:
                if alias in {"ATH", "DT"} and tmdb is None:
                    if mapping_attempted:
                        raise RunnerError("Exact movie mapping remains unknown")
                    mapping_attempted = True
                    tmdb = self.tmdb_movie(imdb)
                evidence[alias] = "absent" if self.absent(alias, imdb, tmdb) else "present"
            except RunnerError as exc:
                evidence[alias] = "unknown"
                self.last_errors[alias] = str(exc)
            if evidence[alias] == "present":
                break
        return evidence

    def check(self, imdb: str) -> dict[str, str]:
        tmdb = None
        if any(t in self.enabled for t in ("ATH", "DT")):
            tmdb = self.tmdb_movie(imdb)
        return {alias: "absent" if self.absent(alias, imdb, tmdb) else "present" for alias in self.enabled}


@contextmanager
def locked_state(path: Path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise RunnerError("State directory must be private (chmod 700) and not a symlink")
    with (path / "runner.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RunnerError("Another catalogue runner is active") from None
        yield


# Docker exec does not reliably propagate client signals to the container child.
# This supervisor kills ONLY its own detached child group on stdin EOF/timeout.
DOCKER_SUPERVISOR = r"""
const {spawn} = require('node:child_process');
const seconds = Number(process.argv[1]);
const child = spawn(process.execPath, process.argv.slice(2), {
  detached: true, stdio: ['ignore', 'inherit', 'inherit']
});
let stopping = false;
function stop() {
  if (stopping) return;
  stopping = true;
  try { process.kill(-child.pid, 'SIGTERM'); } catch (_) {}
  setTimeout(() => { try { process.kill(-child.pid, 'SIGKILL'); } catch (_) {} }, 10000).unref();
}
const timer = setTimeout(stop, seconds * 1000);
process.stdin.resume();
process.stdin.on('end', stop);
process.on('SIGTERM', stop);
process.on('SIGINT', stop);
child.on('error', () => process.exit(127));
child.on('exit', code => { clearTimeout(timer); process.exit(stopping ? 124 : (code ?? 1)); });
"""


def cardinal_argv(settings: dict, arguments: list[str], service: str | None = None) -> list[str]:
    docker = settings.get("cardinal_docker")
    if docker:
        command = [
            settings.get("docker_binary", "docker"),
            "exec",
            "--interactive",
            "--user",
            docker.get("user", "node"),
            "--workdir",
            docker.get("workdir", "/app/.output"),
            docker["container"],
            "node",
            "-e",
            DOCKER_SUPERVISOR,
            str(settings.get("timeout_seconds", 14400)),
            docker.get("cli", "src/cli.js"),
        ]
    else:
        command = [settings.get("cardinal_binary", "cardinaldl")]
    cfg = settings.get("services", {}).get(service, {})
    config = cfg.get("configpath", settings.get("cardinal_configpath"))
    if config:
        command.extend(["--configpath", str(Path(config).expanduser())])
    return command + arguments


def cardinal_command(settings: dict, candidate: dict, profile: dict | None = None) -> list[str]:
    item_id = str(candidate.get("series_item", candidate["item"]))
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", item_id):
        raise RunnerError("Unsafe provider item identifier")
    arguments = ["--service", candidate["service"], "--item", item_id, "--save-to-history"]
    if candidate.get("media_type") == "episode":
        season_id = str(candidate.get("season_id") or candidate["season"])
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", season_id) or type(candidate["episode"]) is not int or candidate["episode"] < 1:
            raise RunnerError("Unsafe or ambiguous episode selector")
        arguments.extend(["--season", season_id, "--episode", str(candidate["episode"])])
    if profile is not None:
        ranges = {
            frozenset(): "sdr",
            frozenset({"DV"}): "dv",
            frozenset({"HDR10"}): "hdr10",
            frozenset({"HDR10+"}): "hdr10+",
            frozenset({"HLG"}): "hlg",
            frozenset({"DV", "HDR10"}): "dv-hdr10",
            frozenset({"DV", "HDR10+"}): "dv-hdr10+",
        }
        mode = settings.get("video_mode", "saved")
        if mode != "saved" and (
            mode not in VIDEO_MODE_HDR or set(profile["hdr"]) != VIDEO_MODE_HDR[mode] or (mode in {"sdr", "hdr10", "hdr10+", "dv", "hlg"} and profile.get("hybrid"))
        ):
            raise RunnerError("Verified profile does not match the requested exact video mode; no fallback permitted")
        dynamic_range = ranges.get(frozenset(profile["hdr"]))
        codec = {"H264": "h264", "H265": "hevc", "AV1": "av1"}.get(profile["codec"])
        if not dynamic_range or not codec:
            raise RunnerError("Selected profile cannot be pinned safely for execution")
        # Snapshot the effective GUI profile for this job; never mutate GUI settings.
        if profile.get("container") not in {"mkv", "mp4"}:
            raise RunnerError("Selected output container could not be verified")
        arguments.extend(
            [
                "--vq",
                f"{profile['resolution']}@{codec}@{dynamic_range}",
                f"--hybrid={'true' if profile.get('hybrid') else 'false'}",
                "--fallback=false",
                "--outputformat",
                profile["container"],
            ]
        )
        for field, flag in (("audio_languages", "--dublang"), ("subtitle_languages", "--dlsubs")):
            values = profile.get(field)
            if values:
                arguments.extend([flag, ",".join(values)])
            elif field == "subtitle_languages" and values == []:
                arguments.append("--nosubs")
    return cardinal_argv(settings, arguments, candidate["service"])


def download(command: list[str], timeout: int) -> str:
    # Do not retain raw Cardinal output: service tokens/URLs can appear in it.
    try:
        # Trusted local executable; service IDs are parsed from allowlisted provider URLs.
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)  # noqa: S603
    except OSError:
        return "failed"
    try:
        code = child.wait(timeout=timeout)
        return "succeeded" if code == 0 else "uncertain" if code == 124 else "failed"
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        # EOF asks the Docker supervisor to terminate its container child group.
        if child.stdin is not None:
            child.stdin.close()
        if DOCKER_SUPERVISOR in command:
            # Keep Docker attached while EOF reaches the container. Killing the client
            # immediately can race its stdin-forwarding thread and orphan the CLI.
            try:
                child.wait(timeout=15)
                return "uncertain"
            except subprocess.TimeoutExpired:
                pass
        # Terminate only our isolated local process group, never existing Cardinal jobs.
        with suppress(ProcessLookupError):
            os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            with suppress(ProcessLookupError):
                os.killpg(child.pid, signal.SIGKILL)
            child.wait()
        return "uncertain"
    finally:
        if child.stdin is not None and not child.stdin.closed:
            child.stdin.close()


def discover(settings: dict, catalogue: Catalogue, store: Store):
    for service, cfg in settings["services"].items():
        region = cfg.get("region", SERVICES[service][1])
        countries = settings.get("origin_countries", [])
        media_types = settings.get("media_types", ["movie"])
        criteria_scope = {
            name: settings.get(name)
            for name in (
                "min_release_year",
                "max_release_year",
                "selection_order",
                "exclude_title_keywords",
                "original_languages",
                "video_mode",
                "discovery_start_offset",
                "min_imdb_votes",
                "max_imdb_votes",
                "min_runtime_minutes",
                "max_runtime_minutes",
            )
        }
        criteria_scope["original_languages"] = sorted(settings.get("original_languages", []))
        key = json.dumps([service, region, sorted(countries), sorted(media_types), criteria_scope], sort_keys=True)
        cursor = store.cursor(key)
        fetched, found = 0, 0
        for _ in range(settings["pages_per_service"]):
            candidates, next_cursor = catalogue.page(service, region, countries, cursor, media_types, settings)
            store.page(key, candidates, next_cursor)
            fetched += 1
            found += len(candidates)
            if next_cursor is None:
                break
            cursor = next_cursor
        print(json.dumps({"status": "discovery_summary", "service": service, "region": region, "pages": fetched, "catalogue_matches": found}), flush=True)


def verify_original_language(settings: dict, trackers, store, candidate: dict) -> bool:
    """Original production language, not localized titles or selected audio tracks."""
    if not settings.get("original_languages"):
        return True
    if trackers is None or not callable(getattr(trackers, "original_language", None)):
        raise RunnerError("Original-language verification is unavailable; no provider request or download permitted")
    language = trackers.original_language(candidate["imdb"], candidate.get("media_type", "movie"))
    candidate["original_language"] = language
    candidate["original_language_source"] = "tmdb_imdb_v1"
    with store.db:
        store.db.execute("UPDATE jobs SET candidate=? WHERE job_key=?", (json.dumps(candidate), candidate.get("job_key", candidate["imdb"])))
    return language in settings["original_languages"]


def process(settings: dict, trackers: Trackers, store: Store, execute: bool):
    if (
        settings.get("verify_cardinal")
        or (settings.get("require_prime_inclusion") and "amazon" in settings.get("services", {}))
        or "tv" in settings.get("media_types", [])
        or settings.get("eligibility", "absent_all") != "absent_all"
        or settings.get("video_mode", "saved") != "saved"
    ):
        from src.catalogue_workflow import process_advanced

        process_advanced(settings, store, execute, inventory=trackers)
        return
    launched = 0
    checked = 0
    # Bound memory and exclude old scopes in SQL, so disabled/changed filters
    # cannot starve the active queue. JSON1 is built into the dedicated SQLite.
    regions = {service: cfg.get("region", SERVICES[service][1]) for service, cfg in settings["services"].items()}
    countries = json.dumps(sorted(settings.get("origin_countries", [])), separators=(",", ":"))
    rows = store.db.execute(
        """SELECT * FROM jobs WHERE status IN ('pending','ready','unknown')
        AND json_extract(?, '$.' || service)=json_extract(candidate,'$.region')
        AND json(coalesce(json_extract(candidate,'$.origin_countries'),'[]'))=?
        AND coalesce(json_extract(candidate,'$.media_type'),'movie')='movie' AND next_check<=?
        ORDER BY coalesce(checked,0),discovered,imdb LIMIT ?""",
        (json.dumps(regions), countries, time.time(), settings["max_checks_per_run"]),
    ).fetchall()
    for row in rows:
        candidate = json.loads(row["candidate"])
        if not selection_matches(candidate, settings):
            store.update(row["imdb"], "filtered", "Excluded by current catalogue year/title criteria")
            continue
        service = candidate["service"]
        if service not in settings["services"] or candidate["region"] != settings["services"][service].get("region", SERVICES[service][1]):
            continue
        if candidate.get("origin_countries", []) != sorted(settings.get("origin_countries", [])):
            continue
        if checked >= settings["max_checks_per_run"]:
            break
        if execute and launched >= settings["max_downloads_per_run"]:
            break
        if time.time() - row["discovered"] > settings["max_candidate_age_hours"] * 3600:
            store.update(row["imdb"], "stale", "Catalogue availability expired; not downloaded")
            continue
        checked += 1
        try:
            evidence = trackers.check(row["imdb"])
        except RunnerError as exc:
            store.update(row["imdb"], "unknown", str(exc))
            print(json.dumps({"imdb": row["imdb"], "status": "unknown", "reason": str(exc)}))
            continue
        if set(evidence) != set(settings["trackers"]) or any(value != "absent" for value in evidence.values()):
            store.update(row["imdb"], "blocked", "Title exists; slot-based eligibility is not implemented", evidence)
            print(json.dumps({"imdb": row["imdb"], "status": "blocked", "trackers": evidence}))
            continue
        try:
            if not verify_original_language(settings, trackers, store, candidate):
                store.update(row["imdb"], "filtered", "Original language does not match the selected catalogue languages")
                continue
        except RunnerError as exc:
            store.update(row["imdb"], "unknown", str(exc))
            continue
        store.update(row["imdb"], "ready", evidence=evidence)
        if not execute:
            print(json.dumps({"imdb": row["imdb"], "status": "ready", "service": service, "item": candidate["item"]}))
            continue
        if launched >= settings["max_downloads_per_run"]:
            break
        disk_path = Path(settings["disk_path"]).expanduser()
        if shutil.disk_usage(disk_path).free < settings["min_free_gib"] * 1024**3:
            print(json.dumps({"status": "paused", "reason": "Minimum free space reached"}))
            break
        # Every launch uses this fresh tracker check, never stored plan evidence.
        if not store.reserve(row["imdb"], service, settings["daily_limit"], settings["services"][service].get("daily_limit", settings["daily_limit"])):
            continue
        launched += 1
        result = download(cardinal_command(settings, candidate), settings["timeout_seconds"])
        store.update(row["imdb"], result, "Cardinal exit status only; payload not independently verified", evidence)
        print(json.dumps({"imdb": row["imdb"], "status": result}))
        if result == "uncertain":
            break


def _interrupt(_signum, _frame):
    raise KeyboardInterrupt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", help="Explicitly permit CardinalDL downloads")
    parser.add_argument("--queue-only", action="store_true", help="Check existing queue, without catalogue discovery")
    args = parser.parse_args(argv)
    old_umask = os.umask(0o077)
    old_term = signal.signal(signal.SIGTERM, _interrupt)
    phase = "configuration"
    try:
        settings, ua = load_settings(args.config)
        if args.execute:
            if settings.get("allow_downloads") is not True:
                raise RunnerError("Set allow_downloads=true as well as --execute to enable downloads")
            binary = settings.get("docker_binary", "docker") if settings.get("cardinal_docker") else settings.get("cardinal_binary", "cardinaldl")
            if not shutil.which(binary):
                raise RunnerError("CardinalDL executable not found on this host")
            if not Path(settings.get("disk_path", "")).is_dir() or not settings.get("disk_path"):
                raise RunnerError("Set disk_path to the filesystem holding Cardinal output/temp files")
        with locked_state(Path(settings["state_dir"]).expanduser()):
            store = Store(Path(settings["state_dir"]).expanduser() / "queue.sqlite3")
            try:
                with httpx.Client(timeout=30, follow_redirects=False, headers={"User-Agent": "UA-CatalogueRunner/0.1"}) as client:
                    from src.catalogue_rate import APIPacer

                    api = API(
                        client,
                        pacer=APIPacer(
                            Path(settings["state_dir"]).expanduser() / "api-rate.sqlite3", settings["tracker_request_interval_seconds"], settings["tracker_daily_api_limit"]
                        ),
                    )
                    if args.execute:
                        total, _ = store.usage()
                        if total >= settings["daily_limit"] or all(
                            store.usage(service)[1] >= cfg.get("daily_limit", settings["daily_limit"]) for service, cfg in settings["services"].items()
                        ):
                            print(json.dumps({"status": "paused", "reason": "Daily global/service start limits reached; no scan started"}))
                            return 0
                    if not args.queue_only:
                        phase = "discovery"
                        discover(settings, Catalogue(api), store)
                    phase = "queue processing"
                    from src.catalogue_diagnostics import selection_summary

                    print(json.dumps({"status": "batch_summary", **selection_summary(store.db, settings)}), flush=True)
                    process(settings, Trackers(api, ua, settings["trackers"]), store, args.execute)
            finally:
                store.db.close()
        return 0
    except KeyboardInterrupt:
        print("Runner interrupted; started jobs will not be automatically replayed.")
        return 130
    except RunnerError as exc:
        print(json.dumps({"status": "error", "phase": phase, "reason": str(exc)}), flush=True)
        print(f"Runner stopped safely: {exc}")
        return 1
    except (OSError, KeyError, TypeError, ValueError, sqlite3.Error):
        # Do not stringify arbitrary config/HTTP exceptions: they can contain secrets.
        print(json.dumps({"status": "error", "phase": phase, "reason": "Configuration, API schema or filesystem failure; no automatic replay of started jobs"}), flush=True)
        print("Runner stopped safely: configuration, API, or filesystem error. No automatic replay of started jobs.")
        return 1
    finally:
        signal.signal(signal.SIGTERM, old_term)
        os.umask(old_umask)


if __name__ == "__main__":
    raise SystemExit(main())

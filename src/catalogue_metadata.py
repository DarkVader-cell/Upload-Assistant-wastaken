"""Sanitized Cardinal listing/profiling interface. No downloads are possible here."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import unicodedata
from pathlib import Path, PurePosixPath

from src.catalogue_runner import DOCKER_SUPERVISOR, VIDEO_MODE_HDR, RunnerError, cardinal_argv, download, video_mode_arguments

CLI_SHA256 = "1963e0217e5dde2593312ba2b61fca089568c613a099d706a0f91ae8b7b3eeba"
PROBE_SOURCE = Path(__file__).resolve().parents[1] / "tools/cardinal-catalogue-probe.cjs"


class PlaybackUnavailableError(RunnerError):
    """Provider supplied no playable full-title offer for the current profile."""


class MetadataStopError(RunnerError):
    """The owned probe was interrupted/timed out; do not start another job."""


def normalized_title(value):
    return "".join(character for character in unicodedata.normalize("NFKC", str(value or "")).casefold() if character.isalnum())


def verify_identity(candidate: dict, listing: dict) -> bool:
    """Exact external ID, or exact title plus matching year/native provider ID."""
    item = listing.get("item")
    if not isinstance(item, dict) or not normalized_title(item.get("title")):
        return False
    imdb = item.get("imdb_id")
    if imdb:
        return imdb == candidate["imdb"]
    if normalized_title(item["title"]) != normalized_title(candidate["title"]):
        return False
    year = item.get("year")
    if year is not None:
        return year == candidate.get("year")
    return str(item.get("id")) == str(candidate["item"])


def planned_profile(item: dict, candidate: dict) -> dict:
    if not isinstance(item, dict):
        raise RunnerError("Cardinal returned no item profile")
    plan = item.get("plan")
    if not isinstance(plan, dict) or plan.get("ok") is not True:
        raise RunnerError("Cardinal could not establish the saved profile's exact available tracks")
    resolution, codec, hdr = plan.get("resolution"), plan.get("codec"), plan.get("hdr")
    if plan.get("container") not in {"mkv", "mp4"}:
        raise RunnerError("Cardinal output-container preference was unavailable")
    if resolution not in {"480p", "540p", "576p", "720p", "1080p", "1440p", "2160p", "4320p"}:
        raise RunnerError("Selected resolution is unsupported by the slot adapter")
    codec = {"H264": "H264", "HEVC": "H265", "H265": "H265", "AV1": "AV1"}.get(codec) if isinstance(codec, str) else None
    if not codec or not isinstance(hdr, list) or any(not isinstance(flag, str) or flag not in {"DV", "HDR10", "HDR10+", "HLG"} for flag in hdr):
        raise RunnerError("Selected codec/dynamic range is unsupported by the slot adapter")
    audio, subtitles = plan.get("audio_languages"), plan.get("subtitle_languages")
    if audio is not None and (
        not isinstance(audio, list) or any(not isinstance(code, str) or not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{2,8})?", code) for code in audio)
    ):
        raise RunnerError("Selected audio languages are invalid")
    if subtitles is not None and (
        not isinstance(subtitles, list) or any(not isinstance(code, str) or not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{2,8})?", code) for code in subtitles)
    ):
        raise RunnerError("Selected subtitle languages are invalid")
    dimensions = {}
    for key in ("video_width", "video_height"):
        value = plan.get(key)
        dimensions[key] = value if type(value) in (int, float) and 0 < value <= 32768 else None
    return {
        "resolution": resolution,
        "codec": codec,
        "hdr": hdr,
        "hybrid": plan.get("hybrid") is True,
        "container": plan["container"],
        **dimensions,
        "provider": {"amazon": "AMZN", "netflix": "NF", "appletv": "ATVP"}[candidate["service"]],
        "audio_languages": audio,
        "subtitle_languages": subtitles,
        "quality": plan.get("quality"),
        "source": "Cardinal saved profile and current manifest",
    }


def episodes_from_listing(candidate: dict, listing: dict, limit: int, include_specials=False, excluded=frozenset()) -> list[dict]:
    if type(limit) is not int or limit < 1:
        raise RunnerError("Episode expansion requires a positive bound")
    if not verify_identity(candidate, listing):
        raise RunnerError("Cardinal series identity did not match the catalogue")
    seasons = listing.get("seasons")
    if not isinstance(seasons, list) or any(not isinstance(entry, dict) or not isinstance(entry.get("episodes"), list) for entry in seasons):
        raise RunnerError("Cardinal returned no valid season inventory")
    if any(entry.get("number") is not None and type(entry["number"]) not in (int, float) for entry in seasons):
        raise RunnerError("Cardinal season numbering was invalid")
    result, seen = [], set()
    for season in sorted(seasons, key=lambda entry: entry.get("number") or 0, reverse=True):
        number = season.get("number")
        if type(number) not in (int, float) or int(number) != number or number < 0 or (number == 0 and not include_specials):
            continue
        for episode in season.get("episodes", []):
            if not isinstance(episode, dict):
                raise RunnerError("Cardinal returned a malformed episode")
            value = episode.get("episode")
            if type(value) not in (int, float) or int(value) != value or value < 1 or (episode.get("is_special") and not include_specials):
                continue
            key = (int(number), int(value))
            if key in seen:
                raise RunnerError("Ambiguous duplicate episode numbering; refusing to guess")
            seen.add(key)
            if not isinstance(episode.get("id"), str) or not episode["id"]:
                continue
            job_key = f"{candidate['imdb']}:S{key[0]:02}E{key[1]:02}"
            if job_key in excluded:
                continue
            result.append(
                {
                    **candidate,
                    "media_type": "episode",
                    "season": key[0],
                    "episode": key[1],
                    "episode_id": episode["id"],
                    "season_id": season.get("id"),
                    "series_item": candidate["item"],
                    "job_key": job_key,
                }
            )
    return result[:limit]


class MetadataProbe:
    def __init__(self, settings: dict):
        self.settings = settings
        self.cache = {}

    def _install(self):
        host = self.settings.get("cardinal_exchange_host")
        container = self.settings.get("cardinal_exchange_container")
        if not host or not container or not self.settings.get("cardinal_docker"):
            raise RunnerError("Configure the dedicated Cardinal metadata exchange mount before advanced discovery")
        host = Path(host).expanduser()
        if not host.is_absolute() or not str(container).startswith("/"):
            raise RunnerError("Metadata exchange paths must be absolute")
        host.mkdir(parents=True, exist_ok=True, mode=0o700)
        if host.is_symlink() or host.stat().st_uid != os.getuid() or host.stat().st_mode & 0o077:
            raise RunnerError("Metadata exchange must be private, owned by this user, and not a symlink")
        source = PROBE_SOURCE.read_bytes()
        name = "probe-" + hashlib.sha256(source).hexdigest()[:20] + ".cjs"
        script = host / name
        if script.exists():
            if script.is_symlink() or script.read_bytes() != source:
                raise RunnerError("Metadata adapter file changed unexpectedly")
        else:
            with script.open("xb") as stream:
                script.chmod(0o600)
                stream.write(source)
        return host, PurePosixPath(container), name

    def list(self, candidate: dict, full=False, season=None) -> dict:
        wanted_episode = candidate.get("episode_id") if full and candidate.get("media_type") == "episode" else None
        cache_key = (candidate["service"], candidate.get("series_item", candidate["item"]), full, season, wanted_episode)
        if cache_key in self.cache:
            return self.cache[cache_key]
        host, container, script = self._install()
        token = "listing-" + secrets.token_hex(16) + ".json"
        output = host / token
        item_id = str(candidate.get('canonical_item') or candidate.get("series_item", candidate["item"]))
        arguments = ["--service", candidate["service"], "--listitem", item_id, "--jsonoutput", str(container / token), "--workers", "1", *video_mode_arguments(self.settings)]
        if full:
            arguments.append("--full")
        if season is not None:
            arguments.extend(["--season", str(season)])
        if wanted_episode:
            arguments.extend(["--ua-episode-id", str(wanted_episode)])
        settings = {**self.settings, "timeout_seconds": min(self.settings.get("metadata_timeout_seconds", 180), self.settings["timeout_seconds"])}
        command = cardinal_argv(settings, arguments, candidate["service"])
        index = command.index(DOCKER_SUPERVISOR) + 2
        cli = self.settings["cardinal_docker"].get("cli", "src/cli.js")
        if not str(cli).startswith("/"):
            cli = str(PurePosixPath(self.settings["cardinal_docker"].get("workdir", "/app/.output")) / cli)
        command[index : index + 1] = [str(container / script), cli]
        try:
            outcome = download(command, settings["timeout_seconds"])
            if outcome == "uncertain":
                raise MetadataStopError("Cardinal metadata interrupted/timed out; this run is stopped")
            if outcome != "succeeded":
                if output.is_file() and not output.is_symlink() and output.stat().st_size <= 8192:
                    failure = json.loads(output.read_text())
                    if (
                        isinstance(failure, dict)
                        and failure.get("schema") == 1
                        and failure.get("cli_sha256") == CLI_SHA256
                        and failure.get("service") == candidate["service"]
                        and failure.get("requested") == item_id
                        and (
                            failure.get("error") == {"code": "playback_unavailable"}
                            or (candidate["service"] == "netflix"
                            and failure.get("error") == {"code": "title_unavailable"})
                        )
                    ):
                        if failure["error"]["code"] == "title_unavailable":
                            raise PlaybackUnavailableError("Netflix returned no video metadata for this exact title under the current profile/region; no download started")
                        raise PlaybackUnavailableError(
                            "Provider returned no playable full-title offer for the current Cardinal account/profile. Check subscription, regional availability and profile access; no download started"
                        )
                raise RunnerError("Cardinal provider listing failed; check its account/profile and availability. No download started")
            if not output.is_file() or output.is_symlink() or output.stat().st_size > 4 * 1024 * 1024:
                raise RunnerError("Cardinal listing was missing or exceeded the safety limit")
            data = json.loads(output.read_text())
            if (
                not isinstance(data, dict)
                or data.get("schema") != 1
                or data.get("cli_sha256") != CLI_SHA256
                or data.get("service") != candidate["service"]
                or data.get("requested") != item_id
            ):
                raise RunnerError("Cardinal metadata contract changed; refusing an unverified selection")
            if data.get("selected_episode") != wanted_episode:
                raise RunnerError("Cardinal returned metadata for a different episode")
            if not isinstance(data.get("seasons"), list) or len(data["seasons"]) > 1000:
                raise RunnerError("Cardinal season inventory exceeded its schema limits")
            for entry in data["seasons"]:
                if not isinstance(entry, dict) or not isinstance(entry.get("episodes"), list) or len(entry["episodes"]) > 20000:
                    raise RunnerError("Cardinal episode inventory was malformed")
            self.cache[cache_key] = data
            return data
        except (OSError, ValueError):
            raise RunnerError("Cardinal metadata file was invalid or inaccessible") from None
        finally:
            # Remove only this request's unpredictable, owned metadata file. No media cleanup.
            output.unlink(missing_ok=True)

    def item_profile(self, candidate: dict) -> dict:
        season = (candidate.get("season_id") or candidate.get("season")) if candidate.get("media_type") == "episode" else None
        listing = self.list(candidate, full=True, season=season)
        if not verify_identity(candidate, listing):
            raise RunnerError("Cardinal media identity did not match the catalogue")
        if candidate.get("media_type") != "episode":
            item = listing.get("item")
        else:
            matches = [
                episode
                for entry in listing.get("seasons", [])
                if entry.get("number") == candidate["season"]
                for episode in entry.get("episodes", [])
                if str(episode.get("id")) == candidate["episode_id"] and episode.get("episode") == candidate["episode"]
            ]
            if len(matches) != 1:
                raise RunnerError("Cardinal episode identity/numbering was ambiguous")
            item = matches[0]
        profile = planned_profile(item, candidate)
        mode = self.settings.get("video_mode", "saved")
        if mode != "saved" and (
            mode not in VIDEO_MODE_HDR or set(profile["hdr"]) != VIDEO_MODE_HDR[mode] or (mode in {"sdr", "hdr10", "hdr10+", "dv", "hlg"} and profile.get("hybrid"))
        ):
            raise RunnerError("Requested video mode is unavailable; no fallback or download permitted")
        return profile

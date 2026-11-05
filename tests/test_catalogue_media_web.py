# ruff: noqa: S101, ARG001, ARG005, RUF059, F811 -- pytest fixtures and protocol-preserving test doubles
"""No real metadata APIs, media transformation or external paths in these tests."""

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from aiohttp import web
from test_catalogue_web import auth, browser, client, config, login, post  # noqa: F401 -- shared aiohttp fixtures

from src.catalogue_media_web import MediaUI, filename_identity
from src.catalogue_runner import locked_state


@pytest.fixture
def manager(tmp_path):
    root = tmp_path / "media"
    root.mkdir(mode=0o700)
    file = root / "Movie.2020.1080p.AMZN.mkv"
    file.write_bytes(b"synthetic-only")

    class Dashboard:
        busy = False
        config_path = tmp_path / "config.json"

        def config(self):
            return {"media_roots": [str(root)], "state_dir": str(tmp_path / "state")}

    value = MediaUI(Dashboard())
    return value, root, file


def identity(tmdb=42):
    return {"tmdb": tmdb, "imdb": f"tt{1234567 + tmdb}", "title": "Movie", "year": 2020, "original_language": "en"}


def fake_tmdb(path, parameters=None):
    if path == "search/movie":
        return {"results": [{"id": 42, "title": "Movie", "release_date": "2020-01-01", "original_title": "Movie"}]}
    if path == "movie/42":
        return {"id": 42, "title": "Movie", "release_date": "2020-01-01", "imdb_id": "tt1234609", "original_language": "en"}
    raise AssertionError("Unexpected API request")


def make_plan(manager, monkeypatch):
    value, root, file = manager
    monkeypatch.setattr(value, "tmdb", fake_tmdb)
    monkeypatch.setattr(
        "src.catalogue_media_web.planned_output", lambda *args, **kwargs: {"filename": "Movie.2020.1080p.AMZN.WEB-DL.DDP5.1.H.264-Kitsune.mkv", "folder": "", "context": {}}
    )
    matched = value.match({"root": 0, "path": file.name}, "owner")
    preview = value.preview({"match_id": matched["match_id"], "tmdb": 42, "provider": "AMZN", "output_root": 0, "output_path": "Processed"}, "owner")
    return value, root, file, preview


@pytest.mark.parametrize(
    "name,title,year",
    [
        ("Movie.2020.1080p.AMZN.mkv", "Movie", 2020),
        ("2001.A.Space.Odyssey.1968.1080p.mkv", "2001 A Space Odyssey", 1968),
        ("Title Without Year.mkv", "Title Without Year", None),
    ],
)
def test_filename_hint(name, title, year):
    assert filename_identity(name) == {"title": title, "year": year}


def test_tv_episode_not_misidentified_as_movie():
    with pytest.raises(ValueError):
        filename_identity("Show.S01E01.2020.mkv")


@pytest.mark.parametrize("path", ["../private.mkv", "/etc/passwd", ".config/private.mkv"])
def test_paths_stay_inside_explicit_roots(manager, path):
    value, _, _ = manager
    with pytest.raises(ValueError):
        value.path(0, path)


def test_symlink_input_not_followed(manager, tmp_path):
    value, root, file = manager
    (root / "link.mkv").symlink_to(file)
    with pytest.raises(ValueError):
        value.path(0, "link.mkv")


def test_exact_match_gets_both_ids_without_processing(manager, monkeypatch):
    value, root, file = manager
    monkeypatch.setattr(value, "tmdb", fake_tmdb)
    result = value.match({"root": 0, "path": file.name}, "owner")
    assert result["selected"]["imdb"] == "tt1234609" and result["selected"]["tmdb"] == 42
    assert not value.busy and file.read_bytes() == b"synthetic-only"


def test_ambiguous_match_never_autoselects(manager, monkeypatch):
    value, root, file = manager
    monkeypatch.setattr(
        value,
        "tmdb",
        lambda *args, **kwargs: {"results": [{"id": 42, "title": "Movie", "release_date": "2020-01-01"}, {"id": 43, "title": "Movie", "release_date": "2020-02-01"}]},
    )
    result = value.match({"root": 0, "path": file.name}, "owner")
    assert result["selected"] is None and result["requires_review"]


def test_plan_is_bound_to_owner_and_file_fingerprint(manager, monkeypatch):
    value, root, file, preview = make_plan(manager, monkeypatch)
    matched = next(iter(value.matches))
    with pytest.raises(ValueError):
        value.preview({"match_id": matched, "tmdb": 42}, "different-session")
    file.write_bytes(b"changed")
    with pytest.raises(ValueError):
        value.preview({"match_id": matched, "tmdb": 42}, "owner")
    assert not (root / "Processed").exists()


@pytest.mark.asyncio
async def test_current_session_preview_required_for_processing(manager, monkeypatch):
    value, root, file, preview = make_plan(manager, monkeypatch)
    with pytest.raises(web.HTTPBadRequest):
        await value.start({"plan_id": preview["plan_id"]}, "different-session")
    assert not value.busy and not (root / "Processed").exists()


@pytest.mark.asyncio
async def test_explicit_job_uses_guarded_cli_and_preserves_source(manager, monkeypatch):
    value, root, file, preview = make_plan(manager, monkeypatch)
    commands = []

    class Child:
        returncode = 0

        async def communicate(self):
            (root / "Processed" / preview["filename"]).write_bytes(b"verified fixture output")
            return json.dumps(
                {
                    "bytes": len(b"verified fixture output"),
                    "executed": True,
                    "privacy_sanitized": True,
                    "metadata_selection_verified": True,
                    "audio_video_hashes_verified": True,
                    "original_retained": True,
                    "output": str(root / "Processed" / preview["filename"]),
                }
            ).encode(), None

    async def launch(*args, **kwargs):
        commands.append(args)
        return Child()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    assert (await value.start({"plan_id": preview["plan_id"]}, "owner"))["started"]
    await value.task
    assert value.job["status"] == "succeeded" and "--execute" in commands[0] and "--imdb" in commands[0]
    assert file.read_bytes() == b"synthetic-only" and (root / "Processed").is_dir()
    with pytest.raises(web.HTTPBadRequest):
        await value.start({"plan_id": preview["plan_id"], "confirmation": "PROCESS COPY"}, "owner")


@pytest.mark.asyncio
async def test_catalogue_busy_blocks_media(manager, monkeypatch):
    value, root, file, preview = make_plan(manager, monkeypatch)
    value.dashboard.busy = True
    with pytest.raises(web.HTTPConflict):
        await value.start({"plan_id": preview["plan_id"], "confirmation": "PROCESS COPY"}, "owner")


@pytest.mark.asyncio
async def test_immediate_cancel_releases_worker_lease(manager, monkeypatch):
    value, root, file, preview = make_plan(manager, monkeypatch)
    await value.start({"plan_id": preview["plan_id"], "confirmation": "PROCESS COPY"}, "owner")
    await value.cancel()
    assert not value.busy and value.lease is None and file.read_bytes() == b"synthetic-only"
    with locked_state(Path(value.dashboard.config()["state_dir"])):
        pass


def test_download_artifact_requires_valid_hash(manager, tmp_path):
    value, root, file = manager
    archive = root / "media-release.pyz"
    archive.write_bytes(b"fixture archive")
    (root / "VALIDATION.json").write_text(json.dumps({"sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}))
    config = value.dashboard.config()
    config["media_tool_archive"] = str(archive)
    value.dashboard.config = lambda: config
    assert value.archive() == archive
    archive.write_bytes(b"tampered")
    with pytest.raises(ValueError):
        value.archive()


@pytest.mark.asyncio
async def test_media_routes_require_login_origin_and_csrf(browser):
    assert (await browser.get("/api/media")).status == 401
    assert (await browser.get("/api/media/tool")).status == 401
    headers = await login(browser)
    assert (await browser.get("/api/media")).status == 200
    assert (await post(browser, "/api/media/files", {"root": 0, "path": ""}, {"Origin": headers["Origin"]})).status == 403
    assert (await post(browser, "/api/media/process", {"plan_id": "made-up", "confirmation": "PROCESS COPY"}, headers)).status == 400


@pytest.mark.asyncio
async def test_media_roots_are_not_browser_editable(browser):
    headers = await login(browser)
    result = await post(browser, "/api/settings", {"settings": {"media_roots": ["/"]}}, headers)
    assert result.status == 400

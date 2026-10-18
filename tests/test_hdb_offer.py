"""HDB offer drafts and image-only pipeline safety (all network is mocked)."""

import importlib
import json
from random import Random
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import requests
from PIL import Image

from src import early_tasks, prep_helpers, takescreens
from src.args import Args, cli_argument_catalog
from src.hdb_offer import generate_hdb_offer, offer_fields, validate_image_bbcode, validate_offer_options
from src.meta import Meta
from src.prep import Prep
from src.screenshot_manifest import clear_group, files as manifest_files, register
from src.temp_paths import screenshots_dir
from src.trackers.hdbits import HDBits

BB = "[url=https://img.hdbits.org/abdce][img]https://img.hdbits.org/a.png[/img][/url]"
CONFIG = {"DEFAULT": {"screens": 3, "img_host_1": "imgbb"}, "TRACKERS": {"HDBITS": {"username": "test-user", "passkey": "test-key"}}}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected network access")
    monkeypatch.setattr(requests.Session, "request", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "request", forbidden)
    monkeypatch.setattr(httpx.Client, "request", forbidden)
    monkeypatch.setattr("socket.socket.connect", forbidden)


@pytest.fixture
def release(tmp_path):
    meta = Meta(hdb_offer=True, base_dir=str(tmp_path), uuid="release", path="/media/release.mkv", category="MOVIE", type="WEBDL", video_codec="AVC", name="Example 2026 1080p WEB-DL", title="Example", year=2026, imdb_id=1234567, tmdb_id=123, screens=3, overview="A film [red]with brackets[/red].")
    directory = tmp_path / "tmp" / meta.uuid
    directory.mkdir(parents=True)
    (directory / "MEDIAINFO_CLEANPATH.txt").write_text("General\nVideo: AVC\n[/hide]", encoding="utf-8")
    screen = screenshots_dir(tmp_path, meta.uuid).joinpath("screen.png")
    screen.write_bytes(b"mock-png")
    register(tmp_path, meta.uuid, [screen], "main")
    return meta


def mock_name(monkeypatch, meta):
    monkeypatch.setattr("src.hdb_offer.NameManager.get_name", AsyncMock(return_value=(meta.name, meta.name, "Example", [])))


@pytest.mark.asyncio
async def test_generate_hdb_offer_image_api_only_and_plaintext_artifacts(release, monkeypatch, capsys):
    release.trackers = ["ULCX", "USENET"]
    mock_name(monkeypatch, release)
    posts = []
    async def post(self, url, data, files):
        assert url == "https://img.hdbits.org/upload_api.php"
        assert data["galleryoption"] == "1"
        screen = manifest_files(release.base_dir, release.uuid, "main")[0]
        assert files == {"images_files[0]": (screen.name, b"mock-png", "image/png")}
        posts.append(url)
        return SimpleNamespace(status_code=200, text=BB)
    monkeypatch.setattr(HDBits, "_post_image_batch", post)
    monkeypatch.setattr(HDBits, "upload", AsyncMock(side_effect=AssertionError("tracker submission")))
    directory = Path(release.base_dir) / "tmp" / release.uuid
    (directory / "description_review.json").write_text('{"content":"[img]https://evil.test/x.png[/img]","source_path":"/media/release.mkv"}')
    paths = await generate_hdb_offer(release, CONFIG)
    assert release.trackers == ["HDBITS"]
    description = paths["HDB_OFFER_DESCRIPTION.txt"].read_text(encoding="utf-8")
    form = paths["HDB_OFFER_FORM.txt"].read_text(encoding="utf-8")
    assert "[hide=MediaInfo]\nGeneral" in description
    assert description.count("[/hide]") == 1 and "［/hide］" in description
    assert "[table" not in description and "evil.test" not in description
    assert "https://www.imdb.com/title/tt1234567/" in description
    assert "https://www.themoviedb.org/movie/123" in description
    assert BB in description
    assert "Category: Movie (1)" in form
    assert "Codec: H.264 (1)" in form and "Medium: WEB-DL (6)" in form
    assert "Origin: External (0)" in form and "Exclusive: No" in form
    assert "TVDB ID: Not available" in form
    assert description in capsys.readouterr().out
    assert posts == ["https://img.hdbits.org/upload_api.php"]
    before = {key: path.read_bytes() for key, path in paths.items()}
    await generate_hdb_offer(release, CONFIG)
    assert {key: path.read_bytes() for key, path in paths.items()} == before


@pytest.mark.asyncio
async def test_offer_fields_tv_and_disc_report(release, monkeypatch):
    release.category, release.season, release.episode = "TV", "S02", "E03"
    release.tvdb_id, release.exclusive, release.tag = 456, True, "-Group"
    config = {"TRACKERS": {"HDBITS": {"username": "test", "passkey": "key", "internal": True, "internal_groups": ["Group"]}}}
    fields = await offer_fields(release, HDBits(config))
    assert fields["Season"] == "2" and fields["Episode"] == "3"
    assert fields["TVDB ID"] == "456" and fields["TMDB link"].endswith("/tv/123")
    assert fields["Origin"] == "Internal (1)" and fields["Exclusive"] == "Yes"
    release.tv_pack = 1
    assert (await offer_fields(release, HDBits(config)))["Episode"] == "Season pack (leave blank)"
    release.is_disc = "BDMV"
    release.discs = [{"type": "BDMV", "summary": "DISC INFO: Example\nVideo: HEVC"}]
    mock_name(monkeypatch, release)
    monkeypatch.setattr(HDBits, "hdbimg_upload", AsyncMock(return_value=BB))
    paths = await generate_hdb_offer(release, config)
    assert "[hide=BDInfo]\nDISC INFO:" in paths["HDB_OFFER_DESCRIPTION.txt"].read_text()


@pytest.mark.parametrize("value", [None, "", "<html>failure</html>", "[img]https://other.test/a.png[/img]", "[url=https://hdbits.org/offer.php][img]https://img.hdbits.org/a.png[/img][/url]", "[img]https://img.hdbits.org.evil.test/a.png[/img]", "[img]https://user@img.hdbits.org/a.png[/img]", "[img]http://img.hdbits.org/a.png[/img]", BB + "[script]x[/script]"])
def test_reject_failed_or_wrong_host_image_responses(value):
    with pytest.raises(ValueError):
        validate_image_bbcode(value)


def test_accept_hdb_gallery_or_image_bbcode():
    assert validate_image_bbcode(BB) == BB
    image = "[img]https://img.hdbits.org/image.png[/img]"
    assert validate_image_bbcode(image) == image
    # Existing HDB description-cleaning contracts recognize this thumbnail host.
    thumbnail = "[url=https://img.hdbits.org/gallery][img]https://t.hdbits.org/thumb.png[/img][/url]"
    assert validate_image_bbcode(thumbnail) == thumbnail


@pytest.mark.parametrize(("field", "value"), [("video_codec", "AV1"), ("type", "UNKNOWN"), ("category", "BOOK"), ("tmdb_id", "../invalid"), ("imdb_id", "javascript:1"), ("name", "bad\nname"), ("name", "[red]title"), ("category", "MUSIC")])
@pytest.mark.asyncio
async def test_invalid_fields_fail_before_images(release, monkeypatch, field, value):
    setattr(release, field, value)
    mock_name(monkeypatch, release)
    uploader = AsyncMock(side_effect=AssertionError("must validate before uploading"))
    monkeypatch.setattr(HDBits, "hdbimg_upload", uploader)
    with pytest.raises(ValueError):
        await generate_hdb_offer(release, CONFIG)
    uploader.assert_not_awaited()


@pytest.mark.parametrize(("field", "value"), [("screens", 0), ("usenet", True), ("site_upload", "HDBITS"), ("site_check", True), ("site_upload_queue", True), ("prepare_only", True), ("dry_run_plan", True), ("cleanup", True), ("skip_imghost_upload", True), ("comparison", "/tmp/comparison")])
def test_reject_incompatible_offer_options(release, field, value):
    setattr(release, field, value)
    with pytest.raises(ValueError):
        validate_offer_options(release)


@pytest.mark.asyncio
async def test_missing_report_or_credentials_fail_before_upload(release, monkeypatch):
    mock_name(monkeypatch, release)
    uploader = AsyncMock()
    monkeypatch.setattr(HDBits, "hdbimg_upload", uploader)
    with pytest.raises(ValueError, match="username and passkey"):
        await generate_hdb_offer(release, {})
    (Path(release.base_dir) / "tmp" / release.uuid / "MEDIAINFO_CLEANPATH.txt").write_text("")
    with pytest.raises(ValueError, match="nonempty"):
        await generate_hdb_offer(release, CONFIG)
    uploader.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_image_upload_writes_no_offer(release, monkeypatch):
    mock_name(monkeypatch, release)
    monkeypatch.setattr(HDBits, "_post_image_batch", AsyncMock(return_value=SimpleNamespace(status_code=403, text="failed")))
    with pytest.raises(ValueError, match="upload failed"):
        await generate_hdb_offer(release, CONFIG)
    assert not list((Path(release.base_dir) / "tmp" / release.uuid).glob("HDB_OFFER_*.txt"))


def test_hdb_offer_cli_and_webui_args(tmp_path):
    media = tmp_path / "release.mkv"
    media.touch()
    parsed, _, _ = Args(CONFIG).parse([str(media), "--hdb-offer", "--tmdb", "movie/123", "--screens", "3"], Meta())
    assert parsed.hdb_offer is True
    assert parsed.tmdb_manual == 123 and parsed.screens == 3
    assert "--hdb-offer" in {item["label"] for item in cli_argument_catalog()}
    from web_ui.server import _validate_upload_assistant_args
    _validate_upload_assistant_args(["--hdb-offer"])


@pytest.mark.asyncio
async def test_prep_offer_branches_before_client_and_early_artifacts(release, monkeypatch):
    prep = Prep.__new__(Prep)
    prep.config, prep.publish_preview = CONFIG, None
    prep._publish_initial_webui_snapshot = AsyncMock()
    prep._capture_early_screenshots = AsyncMock(return_value=release)
    mock_offer_metadata(monkeypatch, release)
    forbidden = AsyncMock(side_effect=AssertionError("normal prep side effect"))
    monkeypatch.setattr(prep_helpers, "process_trackers_and_torrent", forbidden)
    monkeypatch.setattr("src.prep.restart_early_artifact_tasks", forbidden)
    monkeypatch.setattr("src.prep.prepare_artwork", forbidden)
    assert await prep.gather_prep(release, "cli") is release
    prep._capture_early_screenshots.assert_awaited_once()
    assert release.imghost == "hdb"
    forbidden.assert_not_awaited()


def mock_offer_metadata(monkeypatch, release, bdinfo=None):
    monkeypatch.setattr(prep_helpers, "detect_disc_and_category", AsyncMock(return_value=("/media/release.mkv", bdinfo or {})))
    monkeypatch.setattr(prep_helpers, "process_media_files", AsyncMock(return_value=("release", "release", release.path, "release", "file", {}, "release")))
    monkeypatch.setattr(prep_helpers, "calculate_source_size", Mock())
    monkeypatch.setattr(prep_helpers, "validate_media", AsyncMock())
    async def metadata(*args):
        assert release.skip_trackers and not release.keep_images
        assert args[7:10] == (False, False, True)
    monkeypatch.setattr(prep_helpers, "search_metadata", metadata)
    monkeypatch.setattr(prep_helpers, "finalize_metadata", AsyncMock())


class ReachedMetadataStage(Exception):
    pass


@pytest.mark.asyncio
async def test_metadata_offer_skips_tracker_client_and_unit3d_lookups(release, monkeypatch):
    release.is_disc, release.skip_trackers = "BDMV", False
    forbidden = AsyncMock(side_effect=AssertionError("tracker/client lookup"))
    prep = SimpleNamespace(config={"DEFAULT": {"ping_unit3d": True}}, tracker_data_manager=SimpleNamespace(get_tracker_data=forbidden, ping_unit3d=forbidden))
    client = SimpleNamespace(get_ptp_from_hash=forbidden)
    monkeypatch.setattr(prep_helpers.video_manager, "get_type", AsyncMock(side_effect=ReachedMetadataStage))
    with pytest.raises(ReachedMetadataStage):
        await prep_helpers.search_metadata(prep, release, "file", "file", "file", "file", "file", True, True, False, client, {}, {})
    forbidden.assert_not_awaited()


@pytest.mark.asyncio
async def test_metadata_offer_never_enters_bluray_artwork_rehosting(release, monkeypatch):
    release.is_disc = "BDMV"
    forbidden = Mock(side_effect=AssertionError("bluray hosting branch"))
    prep = SimpleNamespace(config={"DEFAULT": {"get_bluray_info": True, "use_bluray_images": True}})
    monkeypatch.setattr(prep_helpers, "_should_fetch_bluray_info", forbidden)
    monkeypatch.setattr(prep_helpers.video_manager, "get_container", AsyncMock(side_effect=ReachedMetadataStage))
    with pytest.raises(ReachedMetadataStage):
        await prep_helpers.finalize_metadata(prep, release, "file", {}, {}, "file", "file", "file")
    forbidden.assert_not_called()


@pytest.mark.asyncio
async def test_offer_early_task_guards_never_create_torrent_or_usenet(release, monkeypatch):
    client = SimpleNamespace(find_existing_torrent=AsyncMock(side_effect=AssertionError("client")))
    forbidden = AsyncMock(side_effect=AssertionError("torrent creation"))
    monkeypatch.setattr("src.early_tasks.TorrentCreator.create_torrent", forbidden)
    with pytest.raises(ValueError, match="cannot start"):
        early_tasks.start_early_artifact_tasks(release, client, CONFIG)
    await early_tasks.create_base_torrents_early(release, client)
    await early_tasks.prepare_usenet_archive_early(release, {"USENET": {}})
    client.find_existing_torrent.assert_not_awaited()
    forbidden.assert_not_awaited()
    assert early_tasks.get_early_artifact_tasks(release.uuid) is None


@pytest.mark.asyncio
async def test_process_meta_offer_skips_normal_pipeline(release, monkeypatch):
    import upload
    prep = SimpleNamespace(gather_prep=AsyncMock(return_value=release))
    monkeypatch.setattr(upload, "Prep", lambda **kwargs: prep)
    monkeypatch.setattr(upload, "config", CONFIG)
    generator = AsyncMock()
    monkeypatch.setattr("src.hdb_offer.generate_hdb_offer", generator)
    monkeypatch.setattr(upload, "write_meta_file", AsyncMock())
    forbidden = AsyncMock(side_effect=AssertionError("normal pipeline"))
    for name in ("gen_desc", "process_trackers", "process_cross_seeds", "validate_tracker_logins"):
        monkeypatch.setattr(upload, name, forbidden)
    assert await upload.process_meta(release, release.base_dir)
    generator.assert_awaited_once_with(release, CONFIG)
    forbidden.assert_not_awaited()


@pytest.mark.parametrize("success", [True, False])
@pytest.mark.asyncio
async def test_outer_offer_loop_never_processes_trackers_crossseeds_clients_or_hooks(release, monkeypatch, success):
    import src.stats as stats
    import upload
    from bin.get_mediainfo import MediaInfoBinaryManager
    media = Path(release.base_dir) / "release.mkv"
    media.touch()
    monkeypatch.setattr(sys, "argv", ["upload.py", str(media), "--hdb-offer"])
    monkeypatch.setattr(importlib, "reload", lambda module: SimpleNamespace(config=CONFIG))
    monkeypatch.setattr(upload, "config", {})
    monkeypatch.setattr(upload, "load_heavy_globals", Mock())
    monkeypatch.setattr(upload, "update_notification", AsyncMock(return_value=None))
    monkeypatch.setattr("src.prowlarr.configured_prowlarr", lambda config: None)
    monkeypatch.setattr("src.configvalidator.validate_config", lambda *args: (True, [], []))
    monkeypatch.setattr(upload, "configured_binary", lambda *args: True)
    monkeypatch.setattr(MediaInfoBinaryManager, "ensure_mediainfo_binary", AsyncMock())
    monkeypatch.setattr(upload, "cleanup_manager", SimpleNamespace(cleanup=AsyncMock(), reset_terminal=Mock()))
    monkeypatch.setattr(upload, "cancel_and_drain_early_artifact_tasks", AsyncMock())
    monkeypatch.setattr(upload, "_publish_webui_preview_target", Mock())
    def parse(args, meta):
        meta.path, meta.hdb_offer, meta.screens = str(media), True, 3
        return meta, None, None
    monkeypatch.setattr(upload, "parser", SimpleNamespace(parse=parse), raising=False)
    monkeypatch.setattr(upload.QueueManager, "handle_queue", AsyncMock(return_value=([str(media)], None)))
    processor = AsyncMock(return_value=success)
    monkeypatch.setattr(upload, "process_meta", processor)
    for name in ("configure_stats", "set_stats_context"):
        monkeypatch.setattr(stats, name, Mock())
    for name in ("record_event_async", "record_release_profile_async"):
        monkeypatch.setattr(stats, name, AsyncMock())
    forbidden = AsyncMock(side_effect=AssertionError("downstream upload side effect"))
    for name in ("process_trackers", "process_cross_seeds", "run_post_upload_hooks", "get_mkbrr_path"):
        monkeypatch.setattr(upload, name, forbidden)
    monkeypatch.setattr(upload, "client", SimpleNamespace(add_to_client=forbidden), raising=False)
    monkeypatch.setattr(upload, "TorrentCreator", SimpleNamespace(create_torrent=forbidden))
    await upload.do_the_thing(release.base_dir)
    processor.assert_awaited_once()
    forbidden.assert_not_awaited()


@pytest.mark.asyncio
async def test_offer_missing_ids_and_tv_ranges_fail_closed(release):
    release.imdb_id, release.tmdb_id = 0, 0
    with pytest.raises(ValueError, match="requires an IMDb or TMDB"):
        await offer_fields(release, HDBits(CONFIG))
    release.imdb_id, release.category = 1234567, "TV"
    release.season, release.episode = "S01-S02", "E03"
    with pytest.raises(ValueError, match="single numeric season"):
        await offer_fields(release, HDBits(CONFIG))
    release.season, release.episode = "S01", "E03E04"
    with pytest.raises(ValueError, match="single numeric episode"):
        await offer_fields(release, HDBits(CONFIG))


@pytest.mark.asyncio
async def test_image_request_error_never_falls_back(release, monkeypatch):
    mock_name(monkeypatch, release)
    monkeypatch.setattr(HDBits, "_post_image_batch", AsyncMock(side_effect=httpx.ConnectError("mock connection failure")))
    with pytest.raises(ValueError, match="upload failed"):
        await generate_hdb_offer(release, CONFIG)
    assert not list((Path(release.base_dir) / "tmp" / release.uuid).glob("HDB_OFFER_*.txt"))


@pytest.mark.parametrize(("value", "expected"), [("true", True), ("1", True), ("TRUE", True), ("false", False), ("0", False), ("False", False)])
@pytest.mark.asyncio
async def test_exclusive_cli_boolean_offer_field(tmp_path, release, value, expected):
    media = tmp_path / "release.mkv"
    media.touch()
    parsed, _, _ = Args(CONFIG).parse([str(media), "--hdb-offer", "--exclusive", value], release)
    assert parsed.exclusive is expected
    fields = await offer_fields(parsed, HDBits(CONFIG))
    assert fields["Exclusive"] == ("Yes" if expected else "No")


@pytest.mark.parametrize("value", ["yes", "no", "2", "invalid", ""])
def test_exclusive_cli_rejects_invalid_boolean(tmp_path, value):
    media = tmp_path / "release.mkv"
    media.touch()
    with pytest.raises(SystemExit):
        Args(CONFIG).parse([str(media), "--hdb-offer", "--exclusive", value], Meta())


@pytest.mark.parametrize("host", ["t.hdbits.org.evil.test", "evil.t.hdbits.org", "user@t.hdbits.org", "t.hdbits.org:443", "hdbits.org", "other.hdbits.org"])
def test_image_bbcode_thumbnail_host_allowlist_is_exact(host):
    with pytest.raises(ValueError):
        validate_image_bbcode(f"[img]https://{host}/thumb.png[/img]")


@pytest.mark.asyncio
async def test_offer_uploader_only_selects_main_manifest_screenshots(release, monkeypatch):
    directory = screenshots_dir(release.base_dir, release.uuid)
    for name in ["stale.png", ".rejected.png", "POSTER.png", "FILE_1.png"]:
        (directory / name).write_bytes(b"must-not-upload")
    other = directory / "playlist.png"
    other.write_bytes(b"must-not-upload")
    register(release.base_dir, release.uuid, [other], "PLAYLIST_1")
    post = AsyncMock(return_value=SimpleNamespace(status_code=200, text=BB))
    monkeypatch.setattr(HDBits, "_post_image_batch", post)
    assert await HDBits(CONFIG).hdbimg_upload(release) == BB
    files = post.call_args.args[2]
    assert files == {"images_files[0]": (manifest_files(release.base_dir, release.uuid, "main")[0].name, b"mock-png", "image/png")}


@pytest.mark.parametrize("capture_result", [None, []])
@pytest.mark.asyncio
async def test_failed_or_empty_offer_capture_leftover_png_never_uploads(release, monkeypatch, capture_result):
    clear_group(release.base_dir, release.uuid, "main")
    screenshots_dir(release.base_dir, release.uuid).joinpath("rejected.png").write_bytes(b"rejected" * 20000)
    prep = Prep.__new__(Prep)
    prep.config, prep.publish_preview = CONFIG, None
    prep.takescreens_manager = SimpleNamespace(screenshots=AsyncMock(return_value=capture_result))
    prep._publish_initial_webui_snapshot = AsyncMock()
    mock_offer_metadata(monkeypatch, release)
    mock_name(monkeypatch, release)
    uploader = AsyncMock(side_effect=AssertionError("must not upload leftover PNG"))
    monkeypatch.setattr(HDBits, "_post_image_batch", uploader)
    with pytest.raises(ValueError, match="no validated registered captures"):
        await prep.gather_prep(release, "cli")
    with pytest.raises(ValueError, match="validated registered screenshots"):
        await generate_hdb_offer(release, CONFIG)
    assert await HDBits(CONFIG).hdbimg_upload(release) is None
    uploader.assert_not_awaited()


@pytest.mark.parametrize(("backend", "capture_mode"), [
    (backend, mode)
    for backend in ("standard", "disc")
    for mode in ("valid", "retry", "rejected", "ffmpeg-failure")
] + [pytest.param("disc", "retry-ffmpeg-failure", id="bdmv-small-initial-all-large-retries-fail")])
@pytest.mark.asyncio
async def test_offer_real_capture_orchestration_with_mocked_ffmpeg(release, monkeypatch, backend, capture_mode):
    """Exercise Prep -> capture/host validation -> manifest -> HDB image API."""
    clear_group(release.base_dir, release.uuid, "main")
    release.screens = 1
    release.filename = "release"
    release.path = str(Path(release.base_dir) / "release.mkv")
    Path(release.path).touch()
    directory = screenshots_dir(release.base_dir, release.uuid)
    # An unrelated leftover must never rescue failed capture or reach the API.
    (directory / "stale.png").write_bytes(b"stale" * 20000)
    (directory.parent / "MediaInfo.json").write_text(json.dumps({"media": {"track": [
        {"Duration": 600}, {"Duration": 600, "Width": 256, "Height": 256, "FrameRate": 24}
    ]}}))
    bdinfo = {}
    if backend == "disc":
        release.is_disc = "BDMV"
        source = directory.parent / "source.m2ts"
        source.touch()
        bdinfo = {"path": str(source.parent), "files": [{"file": source.name, "length": "00:10:00"}],
                  "video": [{"fps": "24 fps", "codec": "AVC", "hdr_dv": ""}]}
        release.discs = [{"type": "BDMV", "summary": "DISC INFO: Example", "bdinfo": bdinfo}]
    prep = Prep.__new__(Prep)
    prep.config, prep.publish_preview = CONFIG, None
    prep.takescreens_manager = takescreens
    prep._publish_initial_webui_snapshot = AsyncMock()
    mock_offer_metadata(monkeypatch, release, bdinfo)
    mock_name(monkeypatch, release)
    monkeypatch.setattr(takescreens, "tone_map", False)
    monkeypatch.setattr(takescreens, "determine_tonemapping", AsyncMock(return_value=False))
    monkeypatch.setattr(takescreens, "record_event_async", AsyncMock())
    # Leave capture_screenshot/capture_disc_task and all validation logic real.
    image = Image.frombytes("RGB", (256, 256), Random(0).randbytes(256 * 256 * 3))
    calls = []
    outcomes = []
    attempts = {}
    async def ffmpeg_stub(command):
        compiled = takescreens.compile_ffmpeg_command(command)
        output = Path(next(arg for arg in compiled if arg.endswith(".png")))
        calls.append(output)
        key = output.stem.removesuffix("-retry")
        attempts[key] = attempts.get(key, 0) + 1
        if capture_mode == "rejected" or (capture_mode in ("retry", "retry-ffmpeg-failure") and attempts[key] == 1):
            Image.new("RGB", (256, 256)).save(output)  # valid PNG, too small
        else:
            image.save(output)
        returncode = int(capture_mode == "ffmpeg-failure" or (capture_mode == "retry-ffmpeg-failure" and attempts[key] > 1))
        outcomes.append((output.stat().st_size, returncode))
        return (returncode, b"", b"mock FFmpeg failure" if returncode else b"")
    monkeypatch.setattr(takescreens, "run_ffmpeg", ffmpeg_stub)
    uploader = AsyncMock(return_value=SimpleNamespace(status_code=200, text=BB))
    monkeypatch.setattr(HDBits, "_post_image_batch", uploader)

    if capture_mode in ("rejected", "ffmpeg-failure", "retry-ffmpeg-failure"):
        with pytest.raises(ValueError, match="no validated registered captures"):
            await prep.gather_prep(release, "cli")
        assert manifest_files(release.base_dir, release.uuid, "main") == []
        with pytest.raises(ValueError, match="validated registered screenshots"):
            await generate_hdb_offer(release, CONFIG)
        assert await HDBits(CONFIG).hdbimg_upload(release) is None
        uploader.assert_not_awaited()
        if capture_mode == "retry-ffmpeg-failure":
            # BDMV captures an extra initial frame, then retries the retained one
            # three times. Failed FFmpeg output must not pass size validation.
            assert len(calls) == 5
            assert all(size <= 75000 and code == 0 for size, code in outcomes[:2])
            assert len(outcomes[2:]) == 3
            assert all(size > 75000 and code != 0 for size, code in outcomes[2:])
            assert all(not output.exists() for output in calls)
            uploader.assert_not_called()
    else:
        assert await prep.gather_prep(release, "cli") is release
        registered = manifest_files(release.base_dir, release.uuid, "main")
        assert len(registered) == 1 and registered[0].stat().st_size > 75000
        await generate_hdb_offer(release, CONFIG)
        uploader.assert_awaited_once()
        files = uploader.call_args.args[2]
        assert files == {"images_files[0]": (registered[0].name, registered[0].read_bytes(), "image/png")}
        expected_initial_calls = 2 if backend == "disc" else 1
        assert len(calls) == expected_initial_calls + (capture_mode == "retry")
    assert calls
    assert (directory / "stale.png").is_file()

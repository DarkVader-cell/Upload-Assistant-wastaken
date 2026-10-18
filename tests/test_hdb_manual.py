"""HDB manual preparation never enters tracker submission or client registration."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from torf import Torrent

from src.args import Args, cli_argument_catalog
from src.clients import Clients
from src.hdb_manual import PLACEHOLDER_ANNOUNCE, allow_manual_after_failed_threshold, manual_announce, prepare_hdb_manual
from src.meta import Meta
from src.stats import completed_item_outcome, tracker_route_outcome
from src.torrent_clients.manual_links import prepare_manual_links
from src.torrent_manifest import TorrentManifest
from src.trackerhandle import process_trackers
from src.trackers.hdbits import HDBits
from src.trackersetup import TrackerSetup
from src.trackerstatus import TrackerStatusManager


@pytest.fixture
def release(tmp_path):
    source = tmp_path / "payload" / "Example.mkv"
    source.parent.mkdir()
    source.write_bytes(b"fictional video data")
    torrent = Torrent(path=source, trackers=["https://other.invalid/SECRET"], private=True, source="OTHER", piece_size=32768)
    torrent.comment = "https://other.invalid/private-release"
    torrent.generate()
    torrent_path = tmp_path / "input.torrent"
    torrent.write(torrent_path)
    TorrentManifest(tmp_path, "release").register(torrent_path, "base", "generated")
    return Meta(base_dir=str(tmp_path), uuid="release", path=str(source), filelist=[str(source)],
                category="MOVIE", name="Example", hdb_manual=True, trackers=["HDBITS"], unattended=True)


@pytest.fixture
def config(tmp_path):
    return {"DEFAULT": {"default_torrent_client": "qbit", "smart_image_host_selection": False, "screens": 3, "img_host_1": "imgbb"},
            "TRACKERS": {"default_trackers": "AITHER,BLUTOPIA", "HDBITS": {"link_dir_name": "HDB"}, "AITHER": {"api_key": "test", "announce_url": "https://other.invalid/announce"}},
            "TORRENT_CLIENTS": {"qbit": {"torrent_client": "qbit", "linking": "hardlink", "linked_folder": [str(tmp_path / "Uploads")]}}}


@pytest.fixture
def forbidden_hdb(monkeypatch):
    forbidden = AsyncMock(side_effect=AssertionError("HDB remote access or registration is forbidden"))
    for name in ("upload", "search_existing", "validate_credentials", "edit_desc"):
        monkeypatch.setattr(HDBits, name, forbidden)
    monkeypatch.setattr("src.cookie_auth.CookieValidator.load_session_cookies", forbidden)
    monkeypatch.setattr(Clients, "add_to_client", forbidden)
    monkeypatch.setattr(Clients, "init_qbittorrent_client", forbidden)
    monkeypatch.setattr(Clients, "_qui_instance_health_check", forbidden)
    monkeypatch.setattr("httpx.AsyncClient", Mock(side_effect=AssertionError("network forbidden")))
    return forbidden


def test_cli_selection_isolates_defaults_and_preserves_explicit_targets(config):
    meta, _, _ = Args(config).parse([".", "--hdb-manual"], Meta())
    assert meta.hdb_manual and meta.trackers == ["HDBITS"]
    assert TrackerSetup(config).trackers_enabled(meta) == ["HDBITS"]
    meta, _, _ = Args(config).parse([".", "--hdb-manual", "-tk", "AITHER,HDB,BLU"], Meta())
    assert meta.trackers == ["AITHER", "HDBITS", "BLUTOPIA"]
    meta, _, _ = Args(config).parse([".", "--hdb-manual", "-tk", "AITHER"], Meta())
    assert meta.trackers == ["AITHER", "HDBITS"]


def test_webui_catalog_and_named_group():
    from web_ui.server import _validate_upload_assistant_args
    assert "--hdb-manual" in {item["label"] for item in cli_argument_catalog()}
    _validate_upload_assistant_args(["--hdb-manual"])
    source = Path("web_ui/static/js/app.js").read_text()
    assert '{ label: "--hdb-manual" }' in source.split('title: "Upload Selection / Dupe"', 1)[1].split('title:', 1)[0]


@pytest.mark.parametrize("args", [["--hdb-offer"], ["--usenet"], ["--site-upload", "HDB"], ["--site-check"],
                                  ["-tk", "MANUAL"], ["--debug"], ["--delete-tmp"], ["--prepare-only"], ["--dry-run-plan"],
                                  ["--cleanup"], ["-tk", "NZBGEEK"], ["--tracker-id", "HDBITS=123"]])
def test_incompatible_modes_rejected(config, args):
    with pytest.raises(ValueError, match="--hdb-manual"):
        Args(config).parse([".", "--hdb-manual", *args], Meta())


@pytest.mark.parametrize("announce", [None, "", "https://other.invalid/passkey", "https://tracker.hdbits.org/<PASSKEY>/announce", "https://fake.tracker", "http://tracker.hdbits.org.evil.invalid/announce"])
def test_announce_never_inherits_another_tracker(announce):
    assert manual_announce({"TRACKERS": {"HDBITS": {"announce_url": announce}}}) == PLACEHOLDER_ANNOUNCE


def test_explicit_real_hdb_announce_is_used():
    url = "https://tracker.hdbits.org/fictional-passkey/announce"
    assert manual_announce({"TRACKERS": {"HDBITS": {"announce_url": url}}}) == url


@pytest.mark.asyncio
async def test_manual_pipeline_exact_torrent_local_links_no_remote_success(release, config, forbidden_hdb, capsys, monkeypatch):
    import upload
    monkeypatch.setattr(upload, "config", config)
    await upload.validate_tracker_logins(release, ["HDBITS"])
    assert await TrackerStatusManager(config).process_all_trackers(release) == 0
    assert release.tracker_status["HDBITS"]["upload"] is False
    assert release.tracker_status["HDBITS"]["manual_pending"] is True
    await process_trackers(release, config, Clients(config), [], {"HDBITS": HDBits}, ["HDBITS"], [])
    output = Path(release.base_dir) / "tmp/release/[HDBITS].torrent"
    actual = Torrent.read(output)
    base = Torrent.read(TorrentManifest(release.base_dir, release.uuid).default_path("base"))
    expected_info = deepcopy(base.metainfo["info"])
    expected_info["source"] = "HDBits"
    assert actual.metainfo["info"] == expected_info
    assert actual.metainfo["announce"] == PLACEHOLDER_ANNOUNCE
    assert "announce-list" not in actual.metainfo
    assert actual.metainfo["comment"] == ""
    assert b"SECRET" not in output.read_bytes()
    linked = Path(release.base_dir) / "Uploads/HDB/Example.mkv"
    assert linked.samefile(release.path)
    status = release.tracker_status["HDBITS"]
    assert status["manual_prepared"] is True and status["upload"] is False and status["upload_success"] is not True
    assert completed_item_outcome([status]) == "no_upload"
    assert tracker_route_outcome(status) == "skipped:no_upload"
    assert not upload.queue_item_has_successful_upload([status])
    assert str(output) in capsys.readouterr().out
    forbidden_hdb.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("remote_allowed", [True, False])
async def test_mixed_tracker_upload_and_client_actions_preserved_or_threshold_blocked(release, config, forbidden_hdb, monkeypatch, remote_allowed):
    release.trackers = ["HDBITS", "AITHER"]
    remote = SimpleNamespace(tracker="AITHER", upload=AsyncMock(return_value=True))
    release.tracker_status = {"HDBITS": {"manual_pending": True, "upload": False}, "AITHER": {"upload": True}}
    if not remote_allowed:
        assert allow_manual_after_failed_threshold(release)
    client = SimpleNamespace(add_to_client=AsyncMock())
    monkeypatch.setattr("src.trackerhandle.check_tracker_image_hosts", AsyncMock())
    await process_trackers(release, config, client, ["AITHER"], {"HDBITS": HDBits, "AITHER": lambda **kw: remote}, ["HDBITS"], [])
    assert release.tracker_status["HDBITS"]["manual_prepared"]
    if remote_allowed:
        remote.upload.assert_awaited_once_with(release)
        client.add_to_client.assert_awaited_once_with(release, "AITHER")
        assert release.tracker_status["AITHER"]["upload_success"] is True
    else:
        remote.upload.assert_not_awaited()
        client.add_to_client.assert_not_awaited()
        assert release.tracker_status["AITHER"]["upload"] is False
    forbidden_hdb.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["qbit", "rtorrent"])
@pytest.mark.parametrize("linking", ["hardlink", "symlink"])
@pytest.mark.parametrize("multi", [False, True])
async def test_linking_exact_layout_and_collision_safety(release, config, forbidden_hdb, kind, linking, multi):
    client_cfg = config["TORRENT_CLIENTS"]["qbit"]
    client_cfg.update(torrent_client=kind, linking=linking)
    source = Path(release.path)
    if multi:
        (source.parent / "Example.srt").write_bytes(b"subtitle")
        (source.parent / "unrelated.txt").write_bytes(b"do not link")
        torrent = Torrent(path=source.parent, exclude_globs=["*.txt"], private=True)
        torrent.name = "Example.Root"
    else:
        torrent = Torrent(path=source, private=True)
    torrent.generate()
    output = Path(release.base_dir) / "test.torrent"
    torrent.write(output)
    expected = Path(release.base_dir) / "Uploads/HDB" / ("Example.Root/Example.mkv" if multi else source.name)
    assert await prepare_manual_links(release, config, output)
    assert expected.samefile(source)
    assert expected.is_symlink() == (linking == "symlink")
    assert not list(expected.parent.glob("unrelated.txt"))
    assert await prepare_manual_links(release, config, output)  # idempotent, validated same inode
    expected.unlink()
    expected.write_bytes(b"collision")
    with pytest.raises(ValueError):
        await prepare_manual_links(release, config, output)
    assert expected.read_bytes() == b"collision" and source.read_bytes() == b"fictional video data"
    forbidden_hdb.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["deluge", "transmission", "watch"])
async def test_no_new_linking_for_other_clients(release, config, forbidden_hdb, kind):
    config["TORRENT_CLIENTS"]["qbit"]["torrent_client"] = kind
    await prepare_hdb_manual(release, config)
    assert not (Path(release.base_dir) / "Uploads").exists()
    forbidden_hdb.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_torrent_is_never_overwritten(release, config):
    output = Path(release.base_dir) / "tmp/release/[HDBITS].torrent"
    output.write_bytes(b"existing artifact")
    with pytest.raises(FileExistsError):
        await prepare_hdb_manual(release, config)
    assert output.read_bytes() == b"existing artifact"


@pytest.mark.asyncio
async def test_crossseed_standalone_never_expands_default_targets(release, config, forbidden_hdb, monkeypatch):
    import upload
    config["DEFAULT"].update(cross_seeding=True, cross_seed_check_everything=True)
    monkeypatch.setattr(upload, "config", config)
    forbidden = AsyncMock(side_effect=AssertionError("cross seed lookup"))
    monkeypatch.setattr(upload, "validate_tracker_logins", forbidden)
    await upload.process_cross_seeds(release)
    forbidden.assert_not_awaited()


@pytest.mark.asyncio
async def test_hdb_metadata_lookup_is_bypassed(release, config, forbidden_hdb):
    from src.get_tracker_data import TrackerDataManager
    release.set_tracker_ids({"HDBITS": "123"})  # also protects IDs automatically discovered in a client comment
    manager = TrackerDataManager(config)
    assert await manager.update_metadata_from_explicit_tracker("HDBITS", HDBits(config), release, "Example", "Example", False) == (release, False)
    forbidden_hdb.assert_not_awaited()


@pytest.mark.asyncio
async def test_manual_output_is_private_even_if_base_is_public(release, config):
    manifest = TorrentManifest(release.base_dir, release.uuid)
    path = manifest.default_path("base")
    base = Torrent.read(path)
    base.private = False
    base.write(path, overwrite=True)
    manifest.register(path, "base", "generated")
    output = await prepare_hdb_manual(release, config)
    assert Torrent.read(output).metainfo["info"]["private"] == 1

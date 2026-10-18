from unittest.mock import AsyncMock

import httpx
import pytest
from torf import Torrent

import src.trackers.hdbits as hdbits_module
from src.meta import Meta
from src.torrent_manifest import TorrentManifest
from src.trackers.common import Common
from src.trackers.hdbits import HDBits

MIB = 1024**2
_REAL_HDB_EDIT_DESC = HDBits.edit_desc


def write_torrent(path, piece_size, size, name="release.mkv"):
    torrent = Torrent()
    count = (size + piece_size - 1) // piece_size
    torrent.metainfo["info"] = {"name": name, "length": size, "piece length": piece_size, "pieces": b"x" * (20 * count)}
    torrent.write(path, overwrite=True)
    return torrent


@pytest.fixture
def setup_release(tmp_path, monkeypatch):
    directory = tmp_path / "tmp" / "release"
    directory.mkdir(parents=True)
    media = tmp_path / "release.mkv"
    media.touch()
    meta = Meta(base_dir=str(tmp_path), uuid="release", path=str(media), filelist=[str(media)], trackers=["HDBITS"], category="MOVIE")
    meta.debug = False
    meta.video = str(media)
    meta.tracker_status = {"HDBITS": {}}
    for filename in ("[HDBITS]DESCRIPTION.txt", "MEDIAINFO_CLEANPATH.txt"):
        (directory / filename).write_text("")
    for method in ("edit_desc", "get_name", "get_type_category_id", "get_type_codec_id", "get_type_medium_id", "get_tags"):
        monkeypatch.setattr(HDBits, method, AsyncMock(return_value=1))
    config = {"DEFAULT": {"default_torrent_client": "none"}, "TORRENT_CLIENTS": {}, "TRACKERS": {"HDBITS": {}}}
    return directory, meta, config


@pytest.mark.asyncio
async def test_successful_upload_records_torrent_id_for_result_link(setup_release, monkeypatch):
    directory, meta, config = setup_release
    source = directory / "candidate.torrent"
    write_torrent(source, 2 * MIB, 4000 * 2 * MIB)
    TorrentManifest(meta.base_dir, meta.uuid).register(source, "base", "client:test")

    monkeypatch.setattr("src.cookie_auth.find_cookie_file", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(Common, "parse_cookie_file", AsyncMock(return_value={}))
    monkeypatch.setattr(HDBits, "download_new_torrent", AsyncMock())

    original_async_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(303, headers={"Location": "https://hdbits.org/details.php?id=12345&uploaded=1"}, request=request)
        return httpx.Response(200, request=request)

    def make_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_async_client(*args, **kwargs)

    monkeypatch.setattr(hdbits_module.httpx, "AsyncClient", make_client)

    assert await HDBits(config).upload(meta) is True  # noqa: S101
    assert meta.tracker_status["HDBITS"]["torrent_id"] == "12345"  # noqa: S101
    assert f"{HDBits.torrent_url}{meta.tracker_status['HDBITS']['torrent_id']}" == "https://hdbits.org/details.php?id=12345"  # noqa: S101


def test_class_exposes_details_url_for_result_links():
    assert HDBits.torrent_url == "https://hdbits.org/details.php?id="  # noqa: S101


@pytest.mark.asyncio
async def test_image_failure_warns_but_does_not_stop_torrent_submission(setup_release, monkeypatch):
    directory, meta, config = setup_release
    source = directory / "candidate.torrent"
    write_torrent(source, 2 * MIB, 4000 * 2 * MIB)
    TorrentManifest(meta.base_dir, meta.uuid).register(source, "base", "client:test")
    monkeypatch.setattr(HDBits, "edit_desc", _REAL_HDB_EDIT_DESC)
    monkeypatch.setattr(HDBits, "hdbimg_upload", AsyncMock(return_value=None))
    monkeypatch.setattr("src.cookie_auth.find_cookie_file", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(Common, "parse_cookie_file", AsyncMock(return_value={}))
    monkeypatch.setattr(HDBits, "download_new_torrent", AsyncMock())
    original_client = httpx.AsyncClient
    posts = []
    def handler(request):
        if request.method == "POST":
            posts.append(str(request.url))
            return httpx.Response(303, headers={"Location": "https://hdbits.org/details.php?id=54321&uploaded=1"}, request=request)
        return httpx.Response(200, request=request)
    def make_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_client(*args, **kwargs)
    monkeypatch.setattr(hdbits_module.httpx, "AsyncClient", make_client)
    assert await HDBits(config).upload(meta) is True
    assert posts == ["https://hdbits.org/upload/upload"]
    assert meta.tracker_status["HDBITS"]["status_message"].startswith("SCREENSHOT WARNING:")
    assert meta.tracker_status["HDBITS"]["torrent_id"] == "54321"

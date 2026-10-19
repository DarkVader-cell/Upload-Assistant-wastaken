"""PTP success results must use the shared clickable tracker-link renderer."""

# ruff: noqa: S101
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from src import trackerhandle
from src.meta import Meta
from src.trackers.common import Common
from src.trackers.GAZELLE.passthepopcorn import PassThePopcorn

TRACKER = "PASSTHEPOPCORN"
DETAILS = "https://passthepopcorn.me/torrents.php?id=9329&torrentid=91868"
LINK = "https://passthepopcorn.me/torrents.php?torrentid=91868"


@pytest.mark.asyncio
async def test_success_records_torrent_id_for_clickable_result(tmp_path, monkeypatch):
    directory = tmp_path / "tmp" / "release"
    directory.mkdir(parents=True)
    (directory / f"[{TRACKER}].torrent").write_bytes(b"synthetic torrent")
    meta = Meta(base_dir=str(tmp_path), uuid="release", tracker_status={TRACKER: {}})
    tracker = PassThePopcorn({"TRACKERS": {TRACKER: {"announce_url": "https://please.passthepopcorn.me/synthetic/announce"}}})
    monkeypatch.setattr(Common, "create_torrent_for_upload", AsyncMock())
    ready = AsyncMock()
    monkeypatch.setattr(Common, "create_torrent_ready_to_seed", ready)
    monkeypatch.setattr("src.cookie_auth.find_cookie_file", lambda *_args: None)
    monkeypatch.setattr(tracker.cookie_validator, "_load_cookies_dict_secure", lambda _path: {})
    original = httpx.AsyncClient

    def handler(request):
        if request.method == "POST":
            return httpx.Response(303, headers={"Location": DETAILS}, request=request)
        return httpx.Response(200, text="Upload completed", request=request)

    def client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    monkeypatch.setattr("src.trackers.GAZELLE.passthepopcorn.httpx.AsyncClient", client)
    assert await tracker.upload(meta, "https://passthepopcorn.me/upload.php", {}) is True
    assert meta.tracker_status[TRACKER]["torrent_id"] == "91868"
    assert tracker.torrent_url + meta.tracker_status[TRACKER]["torrent_id"] == LINK
    assert meta.tracker_status[TRACKER]["status_message"] == DETAILS
    assert ready.await_args.args[-1] == DETAILS


@pytest.mark.asyncio
async def test_ptp_result_uses_same_embedded_link_as_other_trackers(monkeypatch):
    fake = SimpleNamespace(
        tracker=TRACKER, torrent_url=PassThePopcorn.torrent_url, fill_upload_form=AsyncMock(return_value=("unused", {})), upload=AsyncMock(return_value=True)
    )
    monkeypatch.setattr(trackerhandle, "PassThePopcorn", lambda **_kwargs: fake)
    monkeypatch.setattr(trackerhandle, "TrackerSetup", lambda **_kwargs: SimpleNamespace(trackers_enabled=lambda _meta: [TRACKER]))
    monkeypatch.setattr(trackerhandle, "provision_tracker_torrents", AsyncMock())
    monkeypatch.setattr(trackerhandle, "check_tracker_image_hosts", AsyncMock())
    monkeypatch.setattr(trackerhandle, "record_event_async", AsyncMock())
    messages = []
    monkeypatch.setattr(trackerhandle.logger, "info", lambda message, **_kwargs: messages.append(str(message)))
    meta = Meta(
        name="Synthetic release",
        category="MOVIE",
        print_tracker_links=True,
        print_tracker_messages=False,
        tracker_status={TRACKER: {"upload": True, "torrent_id": "91868", "status_message": DETAILS}},
    )
    client = SimpleNamespace(add_to_client=AsyncMock())
    await trackerhandle.process_trackers(
        meta, {"DEFAULT": {"smart_image_host_selection": False, "embed_links": True, "show_upload_duration": False}}, client, [], {}, [], [], bandwidth_control=False
    )
    assert any(f"[link={LINK}]link[/link]" in message for message in messages)
    client.add_to_client.assert_awaited_once()

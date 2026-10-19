"""Transient read recovery must never replay an ambiguous upload mutation."""

# ruff: noqa: S101
import asyncio
import ssl
from unittest.mock import AsyncMock, Mock

import bencodepy
import httpx
import pytest

from src.clients import Clients
from src.meta import Meta
from src.runtime.tracker_requests import TrackerReadError, retry_readonly, safe_upload_retry
from src.trackers.common import Common
from src.trackers.UNIT3D import UNIT3D


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError])
async def test_read_recovers_and_does_not_log_private_url(monkeypatch, error):
    sleep = AsyncMock()
    monkeypatch.setattr("src.runtime.tracker_requests.asyncio.sleep", sleep)
    call = AsyncMock(side_effect=[error("private api_token=secret"), {"data": ["ok"]}])
    assert await retry_readonly(call, "SITE") == {"data": ["ok"]}
    assert call.await_count == 2 and sleep.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404, 422])
async def test_auth_and_validation_reads_do_not_retry(monkeypatch, status):
    sleep = AsyncMock()
    monkeypatch.setattr("src.runtime.tracker_requests.asyncio.sleep", sleep)
    response = httpx.Response(status, request=httpx.Request("GET", "https://example.org/?api_token=secret"))
    error = httpx.HTTPStatusError("private response", request=response.request, response=response)
    call = AsyncMock(side_effect=error)
    with pytest.raises(TrackerReadError) as exc:
        await retry_readonly(call, "SITE")
    assert "secret" not in str(exc.value) and f"HTTP {status}" in str(exc.value)
    assert call.await_count == 1
    sleep.assert_not_called()


@pytest.mark.asyncio
async def test_long_retry_after_is_not_shortened(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr("src.runtime.tracker_requests.asyncio.sleep", sleep)
    response = httpx.Response(429, headers={"Retry-After": "300"}, request=httpx.Request("GET", "https://example.org"))
    call = AsyncMock(side_effect=httpx.HTTPStatusError("limited", request=response.request, response=response))
    with pytest.raises(TrackerReadError, match="longer wait"):
        await retry_readonly(call, "SITE")
    assert call.await_count == 1
    sleep.assert_not_called()


@pytest.mark.asyncio
async def test_cancelled_read_propagates_without_retry():
    call = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await retry_readonly(call, "SITE")
    assert call.await_count == 1


def test_certificate_failure_never_disables_verification_or_retries():
    error = httpx.ConnectError("certificate verify failed")
    error.__cause__ = ssl.SSLCertVerificationError("certificate verify failed")
    assert not safe_upload_retry(error)


@pytest.mark.asyncio
async def test_wrapped_transport_error_retries(monkeypatch):
    monkeypatch.setattr("src.runtime.tracker_requests.asyncio.sleep", AsyncMock())
    wrapped = RuntimeError("provider lookup failed")
    wrapped.__cause__ = httpx.ReadTimeout("timeout")
    call = AsyncMock(side_effect=[wrapped, []])
    assert await retry_readonly(call, "SITE") == [] and call.await_count == 2


def mock_clients(monkeypatch, handler):
    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    monkeypatch.setattr("httpx.AsyncClient", factory)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError])
async def test_upload_ambiguous_failure_is_not_replayed(tmp_path, monkeypatch, failure):
    tracker = UNIT3D({"TRACKERS": {"TEST": {"api_key": "synthetic"}}, "DEFAULT": {"max_retries": 3}}, tracker_name="TEST")
    tracker.upload_url = "https://example.org/upload"
    torrent = tmp_path / "base.torrent"
    torrent.write_bytes(b"synthetic")
    monkeypatch.setattr(tracker, "get_data", AsyncMock(return_value={}))
    monkeypatch.setattr(tracker, "get_additional_files", AsyncMock(return_value={}))
    monkeypatch.setattr(tracker.common, "get_base_torrent_path", AsyncMock(return_value=str(torrent)))
    calls = []

    def handler(request):
        calls.append(request.method)
        raise failure("private token=secret", request=request)

    mock_clients(monkeypatch, handler)
    m = Meta(tracker_status={"TEST": {}}, debug=False)
    assert await tracker.upload(m) is False
    assert calls == ["POST"] and m.tracker_status["TEST"]["upload_outcome_unknown"] is True
    assert "secret" not in m.tracker_status["TEST"]["status_message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 422, 429, 503])
async def test_upload_http_errors_do_not_loop(tmp_path, monkeypatch, status):
    tracker = UNIT3D({"TRACKERS": {"TEST": {}}, "DEFAULT": {"max_retries": 3}}, tracker_name="TEST")
    tracker.upload_url = "https://example.org/upload"
    torrent = tmp_path / "base.torrent"
    torrent.write_bytes(b"synthetic")
    monkeypatch.setattr(tracker, "get_data", AsyncMock(return_value={}))
    monkeypatch.setattr(tracker, "get_additional_files", AsyncMock(return_value={}))
    monkeypatch.setattr(tracker.common, "get_base_torrent_path", AsyncMock(return_value=str(torrent)))
    calls = []

    def handler(request):
        calls.append(request.method)
        return httpx.Response(status)

    mock_clients(monkeypatch, handler)
    m = Meta(tracker_status={"TEST": {}}, debug=False)
    assert await tracker.upload(m) is False and calls == ["POST"]
    assert m.tracker_status["TEST"]["upload_outcome_unknown"] == (status == 503)


@pytest.mark.asyncio
async def test_preconnect_upload_retry_then_accepted_processing_failure_does_not_repost(tmp_path, monkeypatch):
    tracker = UNIT3D({"TRACKERS": {"TEST": {}}, "DEFAULT": {"max_retries": 3}}, tracker_name="TEST")
    tracker.upload_url = "https://example.org/upload"
    torrent = tmp_path / "base.torrent"
    torrent.write_bytes(b"synthetic")
    monkeypatch.setattr(tracker, "get_data", AsyncMock(return_value={}))
    monkeypatch.setattr(tracker, "get_additional_files", AsyncMock(return_value={}))
    monkeypatch.setattr(tracker.common, "get_base_torrent_path", AsyncMock(return_value=str(torrent)))
    monkeypatch.setattr(tracker, "observe_api_key_expiry", lambda *_args: None)
    monkeypatch.setattr(tracker, "process_response_data", AsyncMock(side_effect=ValueError("bad response schema")))
    monkeypatch.setattr("src.trackers.UNIT3D.asyncio.sleep", AsyncMock())
    calls = []

    def handler(request):
        calls.append(request.method)
        if len(calls) == 1:
            raise httpx.ConnectError("before send", request=request)
        return httpx.Response(200, json={"success": True, "data": "https://example.org/torrents/42"})

    mock_clients(monkeypatch, handler)
    m = Meta(tracker_status={"TEST": {}}, debug=False)
    assert await tracker.upload(m) is True and calls == ["POST", "POST"]
    assert m.tracker_status["TEST"]["upload_acknowledged"] is True
    assert "Do not resubmit" in m.tracker_status["TEST"]["status_message"]


@pytest.mark.asyncio
async def test_required_download_failure_defers_client_injection(monkeypatch):
    m = Meta(path="/not-opened", tracker_status={"TEST": {"torrent_download_failed": True}})
    reader = Mock(side_effect=AssertionError("must not open/inject the fallback torrent"))
    monkeypatch.setattr("src.clients.Torrent.read", reader)
    await Clients({}).add_to_client(m, "TEST")
    assert m.tracker_status["TEST"]["client_injection_pending"] is True
    reader.assert_not_called()


class BrokenStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"partial corrupt download"
        raise httpx.ReadError("connection reset with private token")

    async def aclose(self):
        pass


@pytest.mark.asyncio
async def test_torrent_download_retries_atomically(tmp_path, monkeypatch):
    m = Meta(base_dir=str(tmp_path), uuid="release")
    directory = tmp_path / "tmp/release"
    directory.mkdir(parents=True)
    destination = directory / "[TEST].torrent"
    destination.write_bytes(b"original valid local file")
    valid = bencodepy.encode({b"info": {b"name": b"movie", b"piece length": 16384, b"length": 1, b"pieces": b"0" * 20}})
    calls = []

    def handler(request):
        calls.append(request.method)
        assert destination.read_bytes() == b"original valid local file"
        return httpx.Response(200, stream=BrokenStream()) if len(calls) == 1 else httpx.Response(200, content=valid)

    mock_clients(monkeypatch, handler)
    monkeypatch.setattr("src.runtime.tracker_requests.asyncio.sleep", AsyncMock())
    result = await Common({"TRACKERS": {}}).download_tracker_torrent(m, "TEST", downurl="https://example.org/private.torrent")
    assert result == str(destination) and destination.read_bytes() == valid and calls == ["GET", "GET"]
    assert list(directory.glob(".tracker-download-*")) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("html", [True, False])
async def test_failed_or_html_download_preserves_original(tmp_path, monkeypatch, html):
    m = Meta(base_dir=str(tmp_path), uuid="release")
    directory = tmp_path / "tmp/release"
    directory.mkdir(parents=True)
    destination = directory / "[TEST].torrent"
    destination.write_bytes(b"original file")

    def handler(_request):
        return httpx.Response(200, content=b"<html>login required</html>") if html else httpx.Response(200, stream=BrokenStream())

    mock_clients(monkeypatch, handler)
    monkeypatch.setattr("src.runtime.tracker_requests.asyncio.sleep", AsyncMock())
    assert await Common({"TRACKERS": {}}).download_tracker_torrent(m, "TEST", downurl="https://example.org/private?token=secret") is None
    assert destination.read_bytes() == b"original file" and list(directory.glob(".tracker-download-*")) == []

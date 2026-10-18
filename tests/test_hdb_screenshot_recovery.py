"""HDB screenshot errors warn, recover or fall back; they do not abort uploads."""
import io
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from PIL import Image

from src.hdb_images import recover_hosted_images
from src.meta import Meta
from src.trackers.hdbits import HDBits

BB = "[url=https://img.hdbits.org/abc][img]https://t.hdbits.org/abc.jpg[/img][/url]"
CONFIG = {"TRACKERS": {"HDBITS": {"username": "synthetic", "passkey": "synthetic"}}}


@pytest.fixture
def release(tmp_path):
    (tmp_path / "tmp/release").mkdir(parents=True)
    return Meta(base_dir=str(tmp_path), uuid="release", category="MOVIE", name="Example", screens=3)


@pytest.mark.asyncio
async def test_rehost_failure_keeps_existing_images_and_warns(release, monkeypatch):
    release.image_list = [{"raw_url": "https://example.org/full.png", "img_url": "https://example.org/thumb.png", "web_url": "https://example.org/image"}]
    tracker = HDBits(CONFIG)
    monkeypatch.setattr(tracker, "hdbimg_upload", AsyncMock(return_value=None))
    await tracker.edit_desc(release)
    description = Path(release.base_dir, "tmp/release/[HDBITS]DESCRIPTION.txt").read_text()
    assert "https://example.org/thumb.png" in description
    assert release.tracker_status["HDBITS"]["screenshot_warnings"]
    assert "Upload will continue".lower() in Path(release.base_dir, "tmp/release/HDB_SCREENSHOTS_WARNING.txt").read_text().lower()


@pytest.mark.asyncio
async def test_no_images_warns_but_still_writes_description(release, monkeypatch):
    tracker = HDBits(CONFIG)
    monkeypatch.setattr(tracker, "hdbimg_upload", AsyncMock(return_value=None))
    await tracker.edit_desc(release)
    assert Path(release.base_dir, "tmp/release/[HDBITS]DESCRIPTION.txt").exists()
    assert any("No usable screenshot" in x for x in release.tracker_status["HDBITS"]["screenshot_warnings"])


@pytest.mark.asyncio
async def test_unexpected_image_exception_does_not_abort(release, monkeypatch):
    tracker = HDBits(CONFIG)
    monkeypatch.setattr(tracker, "hdbimg_upload", AsyncMock(side_effect=RuntimeError("synthetic image problem")))
    await tracker.edit_desc(release)
    assert Path(release.base_dir, "tmp/release/[HDBITS]DESCRIPTION.txt").exists()


@pytest.mark.asyncio
async def test_partial_or_rejected_bulk_response_retries_individually(release, monkeypatch):
    tracker = HDBits(CONFIG)
    post = AsyncMock(side_effect=[SimpleNamespace(status_code=200, text="{\"error\":\"batch too large\"}"), SimpleNamespace(status_code=200, text=BB), SimpleNamespace(status_code=200, text=BB)])
    monkeypatch.setattr(tracker, "_post_image_batch", post)
    files = {f"images_files[{i}]": (f"{i}.png", b"synthetic", "image/png") for i in range(2)}
    result = await tracker._validated_image_batch("https://img.hdbits.org/upload_api.php", {}, files)
    assert result.count("[img]") == 2
    assert post.await_count == 3
    assert all(list(call.args[2]) == ["images_files[0]"] for call in post.await_args_list[1:])


@pytest.mark.asyncio
async def test_single_image_error_is_not_success(monkeypatch):
    tracker = HDBits(CONFIG)
    monkeypatch.setattr(tracker, "_post_image_batch", AsyncMock(return_value=SimpleNamespace(status_code=200, text="Upload failed")))
    assert await tracker._validated_image_batch("https://img.hdbits.org/upload_api.php", {}, {"images_files[0]": ("a.png", b"x", "image/png")}) is None


@pytest.mark.asyncio
async def test_normal_upload_recovers_cached_hosted_images_but_offer_does_not(release, monkeypatch):
    release.image_list = [{"raw_url": "https://example.org/full.png"}]
    recovered = Path(release.base_dir) / "recovered.png"
    recovered.write_bytes(b"synthetic")
    recovery = AsyncMock(return_value=[recovered])
    monkeypatch.setattr("src.trackers.hdbits.recover_hosted_images", recovery)
    tracker = HDBits(CONFIG)
    post = AsyncMock(return_value=SimpleNamespace(status_code=200, text=BB))
    monkeypatch.setattr(tracker, "_post_image_batch", post)
    assert await tracker.hdbimg_upload(release) == BB
    recovery.assert_awaited_once()
    assert post.await_args.args[2]["images_files[0]"][1] == b"synthetic"
    release.hdb_offer = True
    recovery.reset_mock()
    post.reset_mock()
    assert await tracker.hdbimg_upload(release) is None
    recovery.assert_not_awaited()
    post.assert_not_awaited()


@pytest.mark.asyncio
async def test_bounded_recovery_downloads_full_size_not_gallery(tmp_path, monkeypatch):
    image = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(image, format="PNG")
    requested = []
    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(200, content=image.getvalue(), request=request)
    @asynccontextmanager
    async def client(*args, **kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            yield c
    monkeypatch.setattr("src.hdb_images.shared_http_client", client)
    monkeypatch.setattr("src.hdb_images.assert_public_http_url", AsyncMock())
    files = await recover_hosted_images(tmp_path / "recovery", [{"raw_url": "https://example.org/full.png", "web_url": "https://example.org/gallery", "img_url": "https://example.org/thumb.png"}], 3)
    assert requested == ["https://example.org/full.png"]
    assert len(files) == 1 and files[0].read_bytes() == image.getvalue()
    assert files[0].stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
async def test_recovery_rejects_credentials_and_non_images(tmp_path, monkeypatch):
    requested = []
    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(200, text="Not an image", request=request)
    @asynccontextmanager
    async def client(*args, **kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            yield c
    monkeypatch.setattr("src.hdb_images.shared_http_client", client)
    monkeypatch.setattr("src.hdb_images.assert_public_http_url", AsyncMock())
    assert await recover_hosted_images(tmp_path, [{"raw_url": "https://user:secret@example.org/x.png"}, {"raw_url": "https://example.org/error"}], 3) == []
    assert requested == ["https://example.org/error"]

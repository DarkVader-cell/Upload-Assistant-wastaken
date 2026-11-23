"""Offline regression coverage for tracker screenshot collection."""

# ruff: noqa: S101

import asyncio
from collections import Counter
from io import BytesIO

import httpx
from PIL import Image

from src import trackermeta
from src.meta import Meta


def test_check_images_concurrently_saves_only_verified_response_bytes(monkeypatch, tmp_path):
    buffer = BytesIO()
    Image.new("RGB", (32, 720)).save(buffer, format="PNG")
    png = buffer.getvalue()
    show_url = "https://pixhost.to/show/example/good.png"
    raw_url = "https://img1.pixhost.to/images/example/good.png"
    wrong_mime = "https://example.test/non-image.png"
    corrupt = "https://example.test/corrupt.png"
    responses = {
        raw_url: ("image/png", png),
        wrong_mime: ("text/plain", png),
        corrupt: ("image/png", png[:-12]),  # Intact dimensions but missing the IEND chunk.
    }
    requests = Counter()

    def respond(request):
        url = str(request.url)
        requests[request.method, url] += 1
        mime, body = responses[url]
        return httpx.Response(200, headers={"Content-Type": mime}, content=body)

    client = httpx.AsyncClient

    def offline_client(**kwargs):
        assert kwargs.get("verify", True) is True
        return client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(trackermeta.httpx, "AsyncClient", offline_client)
    monkeypatch.setattr(trackermeta, "expected_images", 5)
    meta = Meta()
    meta.base_dir = str(tmp_path)
    meta.uuid = "example"
    meta.resolution = "720p"
    good = {"raw_url": show_url}
    images = [good, dict(good), {"raw_url": wrong_mime}, {"raw_url": corrupt}, {"raw_url": "https://image.tmdb.org/skipped.png"}]

    result = asyncio.run(trackermeta.check_images_concurrently(images, meta))

    assert requests == {("GET", url): 1 for url in responses}
    assert result == [good]
    assert meta.image_sizes == {raw_url: len(png)}
    directory = tmp_path / "tmp" / meta.uuid
    assert list(directory.iterdir()) == [directory / "good.png"]
    assert (directory / "good.png").read_bytes() == png

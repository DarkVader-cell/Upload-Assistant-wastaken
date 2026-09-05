# ruff: noqa: S101

import asyncio
from typing import Any

from src.meta import Meta
from src.rehostimages import _image_host
from src.trackers.digitalcore import DigitalCore


def test_uses_the_image_hosts_approved_by_digitalcore():
    assert "ptscreens" in DigitalCore.approved_image_hosts
    assert "onlyimage" not in DigitalCore.approved_image_hosts
    assert _image_host("https://img2.ptscreens.com/image.png", DigitalCore.image_host_policy.url_host_mapping) == "ptscreens"


def test_dupe_search_uses_pending_aware_paginated_endpoint() -> None:
    requests: list[dict[str, str | int]] = []

    class Response:
        def __init__(self, payload: dict[str, Any]) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, Any]:
            return self.payload

    class Session:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

        async def get(self, url: str, *, params: dict[str, str | int], **_kwargs: Any) -> Response:
            assert url.endswith("/dupe-search")
            requests.append(dict(params))
            index = int(params["index"])
            if index == 0:
                return Response(
                    {
                        "results": [{"id": 1, "category": 6, "name": "first", "size": 1, "numfiles": 1}],
                        "index": 0,
                        "limit": 100,
                        "count": 1,
                        "total": 2,
                        "includesPending": True,
                    }
                )
            return Response(
                {
                    "results": [{"id": 2, "category": 6, "name": "second", "size": 2, "numfiles": 1}],
                    "index": 1,
                    "limit": 100,
                    "count": 1,
                    "total": 2,
                    "includesPending": True,
                }
            )

    tracker = DigitalCore({"DEFAULT": {}, "TRACKERS": {"DIGITALCORE": {"api_key": "key"}}})
    tracker.session = Session()  # type: ignore[assignment]
    meta = Meta(category="MOVIE", resolution="1080p", imdb="1234567", imdb_tt="tt1234567", name="Movie.2026")

    results = asyncio.run(tracker.search_existing(meta))

    assert [item["name"] for item in results] == ["first", "second"]
    assert requests == [
        {"limit": 100, "index": 0, "imdb": "tt1234567", "releaseName": "Movie.2026"},
        {"limit": 100, "index": 1, "imdb": "tt1234567", "releaseName": "Movie.2026"},
    ]

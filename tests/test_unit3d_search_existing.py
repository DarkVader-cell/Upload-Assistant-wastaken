import asyncio
from typing import Any

import pytest

from src.meta import Meta
from src.trackers.UNIT3D.aither import Aither
from src.trackers.UNIT3D.lst import LST
from src.trackers.UNIT3D.samaritano import Samaritano
from src.trackers.UNIT3D.torrentdesi import DesiTorrents


class FakeResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, list[object]]:
        return {"data": []}


class PaginatedResponse(FakeResponse):
    def __init__(self, data: list[dict[str, object]], next_url: str | None = None) -> None:
        self.data = data
        self.next_url = next_url

    def json(self) -> dict[str, object]:
        return {"data": self.data, "links": {"next": self.next_url}}


class FakeAsyncClient:
    def __init__(self, requests: list[list[tuple[str, Any]]], **_kwargs: Any) -> None:
        self.requests = requests

    async def __aenter__(self) -> FakeAsyncClient:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        pass

    async def get(self, *, url: str, headers: dict[str, str], params: list[tuple[str, Any]]) -> FakeResponse:
        _ = (url, headers)
        self.requests.append(params)
        return FakeResponse()


def test_desitorrents_declares_metadata_id_endpoint() -> None:
    tracker = DesiTorrents({"TRACKERS": {"DESITORRENTS": {}}})

    assert tracker.id_url == "https://torrent.desi/api/v1/torrents/"  # noqa: S101


@pytest.mark.parametrize("tracker_class", [Aither, Samaritano])
def test_tmdb_duplicate_search_omits_category_filter(monkeypatch: pytest.MonkeyPatch, tracker_class: type[Aither] | type[Samaritano]) -> None:
    requests: list[list[tuple[str, Any]]] = []

    def factory(**kwargs: Any) -> FakeAsyncClient:
        return FakeAsyncClient(requests, **kwargs)

    monkeypatch.setattr("src.trackers.UNIT3D.httpx.AsyncClient", factory)

    tracker = tracker_class({"TRACKERS": {tracker_class.tracker: {"api_key": "test-key"}}})
    meta = Meta(category="TV", tmdb=123, season="S01", resolution="1080p", type="WEBDL")

    asyncio.run(tracker.search_existing(meta))

    assert len(requests) == 1  # noqa: S101
    assert ("tmdbId", "123") in requests[0]  # noqa: S101
    assert not any(key == "categories[]" for key, _value in requests[0])  # noqa: S101


def test_missing_tmdb_keeps_category_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[list[tuple[str, Any]]] = []

    def factory(**kwargs: Any) -> FakeAsyncClient:
        return FakeAsyncClient(requests, **kwargs)

    monkeypatch.setattr("src.trackers.UNIT3D.httpx.AsyncClient", factory)

    tracker = Aither({"TRACKERS": {"AITHER": {"api_key": "test-key"}}})
    meta = Meta(category="TV", tmdb=None, season="S01", resolution="1080p", type="WEBDL")

    asyncio.run(tracker.search_existing(meta))

    assert ("categories[]", "2") in requests[0]  # noqa: S101


def test_generic_unit3d_mapping_treats_480i_as_other() -> None:
    tracker = LST({"TRACKERS": {"LST": {}}})

    assert asyncio.run(tracker.get_resolution_id(Meta(resolution="480i"))) == {"resolution_id": "10"}  # noqa: S101


def test_unit3d_duplicate_search_follows_same_origin_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[tuple[str, object]] = []
    responses = [
        PaginatedResponse([{"id": 1, "attributes": {"name": "one", "size": 1, "files": []}}], "https://aither.cc/api/torrents?page=2"),
        PaginatedResponse([{"id": 2, "attributes": {"name": "two", "size": 2, "files": []}}]),
    ]

    class PaginatedClient(FakeAsyncClient):
        async def get(self, *, url: str, headers: dict[str, str], params: object) -> PaginatedResponse:
            _ = headers
            requests.append((url, params))
            return responses.pop(0)

    monkeypatch.setattr("src.trackers.UNIT3D.httpx.AsyncClient", lambda **kwargs: PaginatedClient([], **kwargs))
    tracker = Aither({"DEFAULT": {"unit3d_dupe_max_pages": 5}, "TRACKERS": {"AITHER": {"api_key": "test-key"}}})
    meta = Meta(category="MOVIE", tmdb=123, resolution="1080p", type="WEBDL")

    results = asyncio.run(tracker.search_existing(meta))

    assert [result["name"] for result in results] == ["one", "two"]  # noqa: S101
    assert requests[0][1] is not None  # noqa: S101
    assert requests[1] == ("https://aither.cc/api/torrents?page=2", None)  # noqa: S101


def test_unit3d_duplicate_search_rejects_cross_origin_page(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[tuple[str, object]] = []

    class CrossOriginClient(FakeAsyncClient):
        async def get(self, *, url: str, headers: dict[str, str], params: object) -> PaginatedResponse:
            _ = headers
            requests.append((url, params))
            return PaginatedResponse([], "https://other.example/api/torrents?page=2")

    monkeypatch.setattr("src.trackers.UNIT3D.httpx.AsyncClient", lambda **kwargs: CrossOriginClient([], **kwargs))
    tracker = Aither({"TRACKERS": {"AITHER": {"api_key": "test-key"}}})
    meta = Meta(category="MOVIE", tmdb=123, resolution="1080p", type="WEBDL")

    asyncio.run(tracker.search_existing(meta))

    assert len(requests) == 1  # noqa: S101

# ruff: noqa: S101
"""Bounded queue views, cache invalidation, and international search."""

import json

import pytest

from src.catalogue_runner import Store
from src.catalogue_state import QueueReader


@pytest.fixture
def queue(tmp_path):
    store = Store(tmp_path / "queue.sqlite3")
    candidates = [
        {"imdb": f"tt{index:07}", "title": f"Movie {index}", "service": "netflix" if index % 2 else "amazon", "region": "US", "item": str(index)} for index in range(1, 131)
    ]
    store.page("test", candidates, None)
    yield store, QueueReader(tmp_path / "queue.sqlite3")
    store.db.close()


def test_bounded_pages_and_filters(queue):
    _store, reader = queue
    first = reader.page()
    assert first["total"] == 130 and first["pages"] == 6 and len(first["jobs"]) == 25
    second = reader.page(page=2)
    assert not {job["imdb"] for job in first["jobs"]} & {job["imdb"] for job in second["jobs"]}
    netflix = reader.page(service="netflix", page_size=10)
    assert netflix["total"] == 65 and len(netflix["jobs"]) == 10
    assert all(job["service"] == "netflix" for job in netflix["jobs"])
    assert len(json.dumps(first)) < 15000


def test_cache_reuses_queries_and_invalidates_on_wal_commit(queue, monkeypatch):
    store, reader = queue
    calls = []
    connect = reader._connect

    def counted():
        calls.append(True)
        return connect()

    monkeypatch.setattr(reader, "_connect", counted)
    before = reader.summary()
    assert reader.summary() is before and len(calls) == 1
    store.update("tt0000001", "ready")
    after = reader.summary()
    assert before["revision"] != after["revision"]
    assert after["counts"]["ready"] == 1 and len(calls) == 2


def test_literal_search_and_unicode(queue):
    store, reader = queue
    store.page("new", [{"imdb": "tt9999999", "title": "ÉTÉ 100% Real_Movie", "service": "netflix", "region": "US", "item": "99"}], None)
    assert reader.page(query="%")["total"] == 1
    assert reader.page(query="_")["total"] == 1
    assert reader.page(query="été")["jobs"][0]["imdb"] == "tt9999999"
    assert reader.page(query="tt9999999")["total"] == 1
    assert reader.page(query="' OR 1=1 --")["total"] == 0


@pytest.mark.parametrize("kwargs", [{"page": 0}, {"page": True}, {"page_size": 101}, {"page_size": -1}, {"status": "sql"}, {"service": "invalid"}, {"query": "x" * 121}])
def test_invalid_filters_are_refused(queue, kwargs):
    with pytest.raises(ValueError):
        queue[1].page(**kwargs)


def test_cache_is_bounded(queue):
    reader = queue[1]
    for number in range(50):
        reader.page(query=str(number))
    assert len(reader.cache) <= 32


def test_nonexistent_state_is_read_only(tmp_path):
    path = tmp_path / "missing.sqlite3"
    reader = QueueReader(path)
    assert reader.summary()["total"] == 0 and reader.page()["jobs"] == []
    assert not path.exists()

# ruff: noqa: S101,F401,F811 -- shared fixtures
import pytest
from test_catalogue_state import queue
from test_catalogue_web import auth, browser, client, config, login


def test_empty_nz_scope_explained_without_relaxing_filters(queue):
    store, reader = queue
    settings = {
        "services": {"netflix": {"region": "US"}},
        "origin_countries": ["NZ"],
        "min_release_year": 1970,
        "max_release_year": 2025,
        "min_imdb_votes": 10,
        "max_imdb_votes": 1000,
        "media_types": ["movie"],
    }
    result = reader.selection(settings)
    assert result["eligible"] == 0 and result["queue_total"] == 130
    assert result["filters_relaxed"] is False and result["external_api_requests"] == 0
    assert result["production_countries"] == ["NZ"] and result["services"] == {"netflix": "US"}
    assert "not a provider failure" in result["message"]
    assert store.db.execute("SELECT count(*)FROM attempts").fetchone()[0] == 0


def test_disabled_prime_does_not_block_netflix_and_country_is_not_region(queue):
    store, reader = queue
    candidate = {
        "imdb": "tt9990011",
        "title": "Qualifying Netflix movie",
        "year": 2020,
        "imdb_votes": 100,
        "runtime_minutes": 90,
        "service": "netflix",
        "region": "US",
        "item": "123",
        "origin_countries": ["NZ"],
        "media_type": "movie",
    }
    store.add(candidate)
    store.db.commit()
    settings = {
        "services": {"netflix": {"region": "US"}},
        "origin_countries": ["NZ"],
        "min_release_year": 1970,
        "max_release_year": 2025,
        "min_imdb_votes": 10,
        "max_imdb_votes": 1000,
        "media_types": ["movie"],
        "require_prime_inclusion": True,
    }
    assert reader.selection(settings)["eligible"] == 1
    assert reader.selection({**settings, "origin_countries": []})["eligible"] == 0
    assert reader.selection({**settings, "services": {"netflix": {"region": "NZ"}}})["eligible"] == 0


@pytest.mark.asyncio
async def test_search_context_authenticated_and_local_only(browser):
    assert (await browser.get("/api/search-context")).status == 401
    await login(browser)
    response = await browser.get("/api/search-context")
    assert response.status == 200
    data = await response.json()
    assert data["external_api_requests"] == 0 and data["filters_relaxed"] is False

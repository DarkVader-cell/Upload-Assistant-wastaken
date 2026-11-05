# ruff: noqa: S101
"""Back-catalogue depth and evidence-based obscurity filters, no network."""

from src.catalogue_runner import Catalogue, selection_matches


def edge(number, year=1985, votes=120, runtime=90, released=True):
    return {
        "node": {
            "id": str(number),
            "objectType": "MOVIE",
            "content": {
                "title": f"Fixture {number}",
                "originalReleaseYear": year,
                "scoring": {"imdbVotes": votes},
                "runtime": runtime,
                "isReleased": released,
                "externalIds": {"imdbId": f"tt{8000000 + number}"},
            },
            "offers": [{"monetizationType": "FLATRATE", "standardWebURL": f"https://www.netflix.com/title/{1000 + number}", "package": {"shortName": "nfx"}}],
        }
    }


class FixtureAPI:
    def __init__(self):
        self.calls = []

    def request(self, _method, _url, **kwargs):
        self.calls.append(kwargs["json"])
        return {
            "data": {
                "popularTitles": {
                    "pageInfo": {"endCursor": "MTYw" if len(self.calls) == 1 else "MjAw", "hasNextPage": True},
                    "edges": [edge(1), edge(2, votes=100), edge(3, votes=2000000), edge(4, year=2026), edge(5, votes=None), edge(6, released=False)],
                }
            }
        }


def test_rare_filter_reaches_beyond_front_page_and_requires_known_votes():
    api = FixtureAPI()
    criteria = {
        "discovery_start_offset": 120,
        "min_release_year": 1970,
        "max_release_year": 2015,
        "min_imdb_votes": 10,
        "max_imdb_votes": 5000,
        "min_runtime_minutes": 30,
        "selection_order": "obscure",
    }
    candidates, cursor = Catalogue(api).page("netflix", "US", [], None, criteria=criteria)
    assert [row["imdb_votes"] for row in candidates] == [100, 120]
    assert cursor == "MTYw" and api.calls[0]["variables"]["offset"] == 120
    assert api.calls[0]["variables"]["filter"]["releaseYear"] == {"min": 1970, "max": 2015}
    assert api.calls[0]["variables"]["filter"]["imdbVotes"] == {"min": 10, "max": 5000}
    Catalogue(api).page("netflix", "US", [], cursor, criteria=criteria)
    assert api.calls[1]["variables"]["offset"] == 160


def test_unknown_runtime_and_unreleased_titles_are_not_assumed_eligible():
    base = {"title": "Fixture", "year": 1985, "imdb_votes": 100}
    assert not selection_matches(base, {"min_runtime_minutes": 30})
    assert not selection_matches({**base, "is_released": False}, {})
    assert not selection_matches(base, {"max_runtime_minutes": 120})

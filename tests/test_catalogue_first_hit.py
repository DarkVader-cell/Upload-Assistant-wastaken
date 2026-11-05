# ruff: noqa: S101
"""Never request later trackers or provider manifests after a confirmed hit."""

from src.catalogue_runner import RunnerError, Trackers


def test_first_hit_stops_before_later_trackers(monkeypatch):
    checker = Trackers(None, {}, ["HDB", "PTP", "ATH", "DT"])
    calls = []

    def absent(alias, _imdb, _tmdb):
        calls.append(alias)
        return alias != "PTP"

    monkeypatch.setattr(checker, "absent", absent)
    assert checker.check_until_hit("tt1234567") == {"HDB": "absent", "PTP": "present"}
    assert calls == ["HDB", "PTP"]


def test_unknown_does_not_count_as_absence_but_later_hit_still_blocks(monkeypatch):
    checker = Trackers(None, {}, ["HDB", "PTP", "ATH"])
    calls = []

    def absent(alias, _imdb, _tmdb):
        calls.append(alias)
        if alias == "HDB":
            raise RunnerError("Unknown inventory")
        return False

    monkeypatch.setattr(checker, "absent", absent)
    assert checker.check_until_hit("tt1234567") == {"HDB": "unknown", "PTP": "present"}
    assert calls == ["HDB", "PTP"]

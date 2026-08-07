# ruff: noqa: S101

from src.trackers.adapter import TrackerRegistry


class _Tracker:
    tracker = "DEMO"
    auth_type = "unit3d_api"
    supported_categories = ("MOVIE", "TV")
    is_usenet = False

    def __init__(self, config):
        self.config = config


def test_tracker_registry_normalizes_and_constructs_legacy_factories():
    factories = {"DEMO": _Tracker}
    registry = TrackerRegistry(factories)
    tracker = registry.create(" demo ", {"value": 1})
    assert isinstance(tracker, _Tracker)
    assert tracker.config == {"value": 1}
    assert registry.by_auth_type("unit3d_api") == {"DEMO"}
    assert registry.supports("demo", "movie") is True


def test_tracker_registry_keeps_live_legacy_mapping_compatibility():
    factories = {"DEMO": _Tracker}
    registry = TrackerRegistry(factories)
    factories["SECOND"] = _Tracker
    assert "SECOND" in registry

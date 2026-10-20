from types import SimpleNamespace

import pytest

from src import trackerstatus
from src.meta import Meta


class _Helper:
    prompted = False
    answer = True

    async def prompt_yes_no(self, _message: str, default: bool = False) -> bool:
        del default
        self.prompted = True
        return self.answer


@pytest.mark.asyncio
async def test_failed_additional_check_can_be_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _Helper()
    monkeypatch.setattr(trackerstatus, "UploadHelper", lambda _config: helper)
    monkeypatch.setattr(trackerstatus.sys, "stdin", SimpleNamespace(closed=False, isatty=lambda: False))

    async def check(_meta: Meta) -> bool:
        return False

    result = await trackerstatus.TrackerStatusManager({})._run_additional_checks("TEST", SimpleNamespace(get_additional_checks=check), Meta(), helper)

    assert result is True  # noqa: S101
    assert helper.prompted is True  # noqa: S101


@pytest.mark.asyncio
async def test_failed_additional_check_is_not_overridden_when_stdin_is_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _Helper()
    monkeypatch.setattr(trackerstatus, "UploadHelper", lambda _config: helper)
    monkeypatch.setattr(trackerstatus.sys, "stdin", SimpleNamespace(closed=True))

    async def check(_meta: Meta) -> bool:
        return False

    result = await trackerstatus.TrackerStatusManager({})._run_additional_checks("TEST", SimpleNamespace(get_additional_checks=check), Meta(), helper)

    assert result is False  # noqa: S101
    assert helper.prompted is False  # noqa: S101


@pytest.mark.asyncio
async def test_failed_additional_check_is_not_overridden_when_prompt_reaches_eof(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _Helper()
    monkeypatch.setattr(trackerstatus, "UploadHelper", lambda _config: helper)

    async def prompt_yes_no(_message: str, default: bool = False) -> bool:
        del default
        helper.prompted = True
        raise EOFError

    monkeypatch.setattr(helper, "prompt_yes_no", prompt_yes_no)

    async def check(_meta: Meta) -> bool:
        return False

    result = await trackerstatus.TrackerStatusManager({})._run_additional_checks("TEST", SimpleNamespace(get_additional_checks=check), Meta(), helper)

    assert result is False  # noqa: S101
    assert helper.prompted is True  # noqa: S101


@pytest.mark.asyncio
async def test_failed_additional_check_is_skipped_in_unattended_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _Helper()
    monkeypatch.setattr(trackerstatus, "UploadHelper", lambda _config: helper)

    async def check(_meta: Meta) -> bool:
        return False

    result = await trackerstatus.TrackerStatusManager({})._run_additional_checks("TEST", SimpleNamespace(get_additional_checks=check), Meta(unattended=True), helper)

    assert result is False  # noqa: S101
    assert helper.prompted is False  # noqa: S101


@pytest.mark.asyncio
async def test_full_ptp_status_to_slot_skip_keeps_concrete_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePTP:
        tracker = "PASSTHEPOPCORN"
        banned_groups = ()

        def __init__(self, config):
            self.config = config

        async def get_additional_checks(self, _meta):
            return True

        async def get_group_by_imdb(self, *_args, **_kwargs):
            return 1

        async def search_existing(self, _group_id, _meta):
            return [{"id": 42, "name": "Film.2020.1080p.BluRay.x264-OLD", "link": "https://example.test/torrents/42"}]

        async def get_name(self, meta):
            return {"name": meta.name}

    class FakeSetup:
        def __init__(self, config):
            self.config = config

        def filter_unsupported_trackers(self, _meta):
            return None

        async def check_banned_group(self, *_args):
            return False

        async def get_torrent_claims(self, *_args):
            return False

    class FakeDupes:
        def __init__(self, _config):
            pass

        async def filter_dupes(self, dupes, _meta, _tracker):
            return dupes

    monkeypatch.setattr(trackerstatus, "tracker_class_map", {"PASSTHEPOPCORN": FakePTP})
    monkeypatch.setattr(trackerstatus, "PassThePopcorn", FakePTP)
    monkeypatch.setattr(trackerstatus, "TrackerSetup", FakeSetup)
    monkeypatch.setattr(trackerstatus, "DupeChecker", FakeDupes)
    async def event(*_args, **_kwargs):
        return None

    monkeypatch.setattr(trackerstatus, "record_event_async", event)
    monkeypatch.setattr(trackerstatus, "logger", SimpleNamespace(info=lambda *_args, **_kwargs: None, warning=lambda *_args, **_kwargs: None, debug=lambda *_args, **_kwargs: None))
    monkeypatch.setattr("src.uphelper.logger.info", lambda *_args, **_kwargs: None)

    meta = Meta(
        category="MOVIE",
        name="Film.2020.1080p.BluRay.x264-NEW",
        title="Film",
        type="ENCODE",
        source="BluRay",
        resolution="1080p",
        video_codec="AVC",
        imdb_id=123,
        imdb="123",
        imdb_info={"type": "movie"},
        trackers=["PASSTHEPOPCORN"],
        tracker_status={"PASSTHEPOPCORN": {}},
        unattended=True,
    )
    result = await trackerstatus.TrackerStatusManager({"DEFAULT": {}, "TRACKERS": {}}).process_all_trackers(meta)
    assert result == 0
    status = meta.tracker_status["PASSTHEPOPCORN"]
    assert status["skipped"] is True
    assert "second encode" in status["skip_reason"].lower()
    assert "supplied PTP rules" not in status["skip_reason"]

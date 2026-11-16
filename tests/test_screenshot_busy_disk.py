"""Busy-disk capture retries remain bounded and do not register failed frames."""
import pytest

from src import takescreens
from src.meta import Meta


@pytest.mark.asyncio
@pytest.mark.parametrize("succeeds", [True, False])
async def test_capture_retries_timeout_once(tmp_path, monkeypatch, succeeds):
    source = tmp_path / "video.mkv"
    source.touch()
    output = tmp_path / "screen.png"
    calls = []

    async def run(_command):
        calls.append(1)
        if succeeds and len(calls) == 2:
            output.touch()
            return 0, b"", b""
        raise TimeoutError

    async def no_sleep(_seconds):
        pass

    monkeypatch.setattr(takescreens, "run_ffmpeg", run)
    monkeypatch.setattr(takescreens.asyncio, "sleep", no_sleep)
    result = await takescreens.capture_screenshot((0, str(source), 1.0, str(output), 1280, 720, 1, 1, "quiet", False, Meta()))
    assert len(calls) == 2
    assert result == (0, str(output) if succeeds else None)


@pytest.mark.asyncio
@pytest.mark.parametrize(("configured", "expected"), [(None, 1800), (2400, 2400), (999999, 86400), ("invalid", 1800)])
async def test_capture_timeout_is_configurable_and_bounded(tmp_path, monkeypatch, configured, expected):
    source = tmp_path / "video.mkv"
    source.touch()
    output = tmp_path / "screen.png"
    seen = []

    async def run(_command):
        output.touch()
        return 0, b"", b""

    async def wait_for(coroutine, timeout):
        seen.append(timeout)
        return await coroutine

    monkeypatch.setattr(takescreens, "default_config", {"screenshot_capture_timeout": configured})
    monkeypatch.setattr(takescreens, "run_ffmpeg", run)
    monkeypatch.setattr(takescreens.asyncio, "wait_for", wait_for)
    result = await takescreens.capture_screenshot((0, str(source), 1.0, str(output), 1280, 720, 1, 1, "quiet", False, Meta()))
    assert result == (0, str(output))
    assert seen == [expected]

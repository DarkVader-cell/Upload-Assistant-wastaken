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

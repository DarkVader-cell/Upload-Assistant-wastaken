# ruff: noqa: S101

import asyncio
import sys

from src.cleanup import CleanupManager
from src.meta import Meta
from src.metadata_cache import cache_for
from src.runtime.context import ExecutionContext, current_execution_context
from src.runtime.http import HttpClientPool, shared_http_client
from src.runtime.pipeline import FunctionStage, Pipeline, StageResult, StageStatus
from src.runtime.subprocesses import SubprocessManager


def test_metadata_cache_reuses_compatible_instances(tmp_path):
    config = {"DEFAULT": {"metadata_cache_dir": "cache"}}
    assert cache_for(tmp_path, config) is cache_for(tmp_path, config)


def test_http_pool_reuses_clients_and_coalesces_operations():
    async def run() -> None:
        pool = HttpClientPool()
        first = await pool.client("metadata", request_timeout=10, headers={"User-Agent": "ua"})
        second = await pool.client("metadata", request_timeout=10, headers={"user-agent": "ua"})
        assert first is second

        calls = 0
        release = asyncio.Event()

        async def operation() -> object:
            nonlocal calls
            calls += 1
            await release.wait()
            return object()

        tasks = [asyncio.create_task(pool.coalesce("provider:item", operation)) for _ in range(3)]
        await asyncio.sleep(0)
        release.set()
        values = await asyncio.gather(*tasks)
        assert calls == 1
        assert values[0] is values[1] is values[2]
        await pool.close()

    asyncio.run(run())


def test_http_pool_releases_coalesced_work_after_all_callers_cancel():
    async def run() -> None:
        pool = HttpClientPool()
        started = asyncio.Event()
        release = asyncio.Event()

        async def operation() -> None:
            started.set()
            await release.wait()

        caller = asyncio.create_task(pool.coalesce("provider:cancelled", operation))
        await started.wait()
        caller.cancel()
        await asyncio.gather(caller, return_exceptions=True)
        release.set()
        for _ in range(3):
            if not pool._inflight:
                break
            await asyncio.sleep(0)
        assert not pool._inflight
        await pool.close()

    asyncio.run(run())


def test_pipeline_preserves_order_observes_results_and_stops(tmp_path):
    async def run() -> None:
        context = ExecutionContext.create(tmp_path, {}, metrics_enabled=True)
        meta = Meta()
        calls: list[str] = []

        async def first(_context, _meta):
            calls.append("first")
            return StageResult.completed()

        async def stop(_context, _meta):
            calls.append("stop")
            return StageResult.stopped("done")

        async def never(_context, _meta):
            calls.append("never")
            return StageResult.completed()

        observed: list[tuple[str, StageStatus]] = []
        pipeline = Pipeline(
            [FunctionStage("first", first), FunctionStage("stop", stop), FunctionStage("never", never)],
            observers=[lambda name, result, _elapsed: observed.append((name, result.status))],
        )
        results = await pipeline.run(context, meta)
        assert calls == ["first", "stop"]
        assert [result.status for result in results] == [StageStatus.COMPLETED, StageStatus.STOPPED]
        assert observed == [("first", StageStatus.COMPLETED), ("stop", StageStatus.STOPPED)]
        assert context.metrics.snapshot()["timings"]
        await context.close()

    asyncio.run(run())


def test_execution_context_scopes_shared_http_clients(tmp_path):
    async def run() -> None:
        context = ExecutionContext.create(tmp_path, {})
        assert current_execution_context() is None
        async with context:
            assert current_execution_context() is context
            async with shared_http_client("provider") as first, shared_http_client("provider") as second:
                assert first is second
        assert current_execution_context() is None

    asyncio.run(run())


def test_subprocess_manager_captures_output_and_rejects_use_after_close():
    async def run() -> None:
        manager = SubprocessManager(concurrency=1)
        result = await manager.run([sys.executable, "-c", "print('ready')"])
        assert result.returncode == 0
        assert result.stdout.strip() == b"ready"
        await manager.close()
        try:
            await manager.run([sys.executable, "-c", "pass"])
        except RuntimeError:
            return
        raise AssertionError("closed subprocess manager accepted work")

    asyncio.run(run())


def test_subprocess_manager_does_not_start_queued_work_after_close():
    async def run() -> None:
        manager = SubprocessManager(concurrency=1)
        await manager._semaphore.acquire()
        queued = asyncio.create_task(manager.run([sys.executable, "-c", "raise SystemExit(99)"]))
        await asyncio.sleep(0)
        await manager.close()
        manager._semaphore.release()
        result = await asyncio.gather(queued, return_exceptions=True)
        assert isinstance(result[0], RuntimeError)

    asyncio.run(run())


def test_legacy_cleanup_keeps_unrelated_event_loop_tasks_running(monkeypatch):
    async def run() -> None:
        cleanup = CleanupManager()
        monkeypatch.setattr(cleanup, "kill_all_threads", lambda: None)
        release = asyncio.Event()
        unrelated = asyncio.create_task(release.wait())
        await cleanup.cleanup()
        assert not unrelated.done()
        release.set()
        await unrelated

    asyncio.run(run())

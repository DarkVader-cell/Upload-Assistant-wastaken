# ruff: noqa: S101

import asyncio
import json

from flask import Flask

from src.args import Args
from src.extensions import ExtensionRegistry, load_extensions
from src.meta import Meta
from src.queuemanage import QueueManager
from src.runtime.artifacts import ArtifactStore, preparation_key
from src.runtime.context import ExecutionContext
from src.runtime.health import collect_runtime_health
from src.runtime.pipeline import FunctionStage, Pipeline, StageResult, StageStatus
from src.runtime.planner import build_execution_plan, preparation_pipeline_signature
from src.runtime.queue import SafeParallelPreparation
from src.runtime.scheduler import AdaptiveScheduler
from src.trackers.adapter import TrackerRegistry
from web_ui.services.qui_sync import QuiEventBroker, create_qui_sync_blueprint
from web_ui.services.runtime_api import create_runtime_api_blueprint


def test_content_addressed_artifacts_deduplicate_restore_and_redact(tmp_path):
    async def run() -> None:
        config = {"DEFAULT": {"preparation_artifacts_dir": "cache/artifacts"}}
        store = ArtifactStore(tmp_path, config)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "release.torrent").write_bytes(b"torrent payload")
        (workspace / "meta.json").write_text("{}", encoding="utf-8")

        assert await store.capture("release-key", workspace, {"title": "Release", "api_key": "do-not-store"})
        assert await store.capture("release-key", workspace, {"title": "Release", "api_key": "do-not-store"})
        assert store.stats() == {"entries": 1, "objects": 1, "bytes": len(b"torrent payload")}

        restored = tmp_path / "restored"
        snapshot = await store.restore("release-key", restored)
        assert snapshot == {"title": "Release"}
        assert (restored / "release.torrent").read_bytes() == b"torrent payload"
        assert json.loads((restored / "meta.json").read_text(encoding="utf-8")) == {"title": "Release"}
        (restored / "release.torrent").write_bytes(b"changed downstream")
        second_restore = tmp_path / "restored-again"
        await store.restore("release-key", second_restore)
        assert (second_restore / "release.torrent").read_bytes() == b"torrent payload"

    asyncio.run(run())


def test_pipeline_resumes_completed_stages_without_rerunning(tmp_path):
    async def run() -> None:
        config = {"DEFAULT": {"stage_checkpoints_dir": "cache/checkpoints"}}
        async with ExecutionContext.create(tmp_path, config) as context:
            calls = 0

            async def prepare(_context, meta):
                nonlocal calls
                calls += 1
                meta.title = "Checkpointed"
                return StageResult.completed("saved")

            first = Pipeline(
                [FunctionStage("prepare", prepare)],
                checkpoint_store=context.checkpoints,
                run_key="release",
                signature="test-v1",
            )
            first_results = await first.run(context, Meta(archive_password="must-not-persist"))  # noqa: S106
            resumed_meta = Meta(archive_password="current-invocation")  # noqa: S106
            second_results = await first.run(context, resumed_meta)

            assert calls == 1
            assert first_results[0].status is StageStatus.COMPLETED
            assert second_results[0].status is StageStatus.SKIPPED
            assert resumed_meta.title == "Checkpointed"
            assert resumed_meta.archive_password == "current-invocation"  # noqa: S105
            assert "must-not-persist" not in context.checkpoints.path_for("release").read_text(encoding="utf-8")

    asyncio.run(run())


def test_execution_plan_reports_artifact_and_checkpoint_hits(tmp_path):
    async def run() -> None:
        source = tmp_path / "video.mkv"
        source.write_bytes(b"video")
        config = {
            "DEFAULT": {
                "preparation_artifacts_dir": "cache/artifacts",
                "stage_checkpoints_dir": "cache/checkpoints",
            },
            "TRACKERS": {"default_trackers": ["AITHER", "BLU"]},
        }
        meta = Meta()
        key = preparation_key(source, meta, preparation_pipeline_signature())
        async with ExecutionContext.create(tmp_path, config) as context:
            artifact_workspace = tmp_path / "prepared"
            artifact_workspace.mkdir()
            (artifact_workspace / "meta.json").write_text("{}", encoding="utf-8")
            await context.artifacts.capture(key, artifact_workspace, {"title": "Cached"})
            await context.checkpoints.mark_completed(
                key,
                preparation_pipeline_signature(),
                "gather_initial_metadata",
                {"title": "Checkpointed"},
            )
            plan = await build_execution_plan(context, meta, source)

            stages = {stage.name: stage for stage in plan.stages}
            assert plan.trackers == ("AITHER", "BLU")
            assert stages["restore_preparation_artifacts"].cache_hit
            assert stages["gather_initial_metadata"].cache_hit
            assert plan.resumable

    asyncio.run(run())


def test_adaptive_scheduler_serializes_provider_mutations_and_persists(tmp_path):
    async def run() -> None:
        config = {"DEFAULT": {"adaptive_scheduler_state": "cache/scheduler.json", "adaptive_scheduler_concurrency": 4}}
        scheduler = AdaptiveScheduler(tmp_path, config)
        active = 0
        peak = 0

        async def operation() -> str:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return "done"

        values = await asyncio.gather(
            scheduler.run("tracker:A", operation, serialize_mutation=True),
            scheduler.run("tracker:A", operation, serialize_mutation=True),
        )
        scheduler.record("slow", 5.0, success=False, status=500)
        scheduler.record("fast", 0.01, success=True, status=200)
        assert values == ["done", "done"]
        assert peak == 1
        assert scheduler.ordered(["slow", "fast"]) == ["fast", "slow"]
        await scheduler.close()
        persisted = json.loads((tmp_path / "cache" / "scheduler.json").read_text(encoding="utf-8"))
        assert persisted["providers"]["tracker:A"]["requests"] == 2

    asyncio.run(run())


def test_extensions_are_opt_in_and_reject_conflicts(tmp_path):
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "sample.py").write_text(
        "def register(registry):\n"
        "    registry.register_tracker('XX', object)\n"
        "    registry.register_provider('META', object())\n"
        "    registry.register_health_check('PING', lambda: {'healthy': True})\n",
        encoding="utf-8",
    )
    disabled = load_extensions(tmp_path, {"DEFAULT": {"extensions_enabled": False}}, force=True)
    enabled = load_extensions(
        tmp_path,
        {"DEFAULT": {"extensions_enabled": True, "extension_paths": ["plugins"]}},
        force=True,
    )
    assert disabled.trackers == {}
    assert enabled.loaded == ["file:sample.py"]
    assert set(enabled.trackers) == {"XX"}
    assert enabled.health_checks["PING"]() == {"healthy": True}

    registry = ExtensionRegistry()
    registry.register_tracker("XX", object)
    try:
        registry.register_tracker("XX", object)
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate extension tracker was accepted")

    try:
        TrackerRegistry({"XX": object}, enabled.trackers)
    except ValueError:
        pass
    else:
        raise AssertionError("extension tracker shadowed a built-in")


def test_health_snapshot_exposes_capabilities_without_credentials(tmp_path):
    config = {
        "DEFAULT": {"extensions_enabled": False},
        "TORRENT_CLIENTS": {
            "qbit": {
                "torrent_client": "qbit",
                "qui_api_url": "http://qui.invalid",
                "qui_api_key": "secret-value",
                "qui_instance_id": "instance",
            }
        },
    }
    health = collect_runtime_health(tmp_path, config)
    encoded = json.dumps(health)
    assert health["clients"]["qbit"]["qui_native"]
    assert "secret-value" not in encoded
    assert set(health) == {"status", "generated_at", "cache", "checkpoints", "scheduler", "clients", "tools", "extensions"}


def test_safe_parallel_preparation_bounds_work_and_serializes_mutations():
    async def run() -> None:
        pool: SafeParallelPreparation[int, int] = SafeParallelPreparation(concurrency=2)
        active = 0
        preparation_peak = 0
        mutation_order: list[int] = []

        async def prepare(item: int) -> int:
            nonlocal active, preparation_peak
            active += 1
            preparation_peak = max(preparation_peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return item * 2

        assert await pool.prepare([1, 2, 3, 4], prepare) == [2, 4, 6, 8]

        async def mutate(item: int) -> None:
            async def operation() -> None:
                mutation_order.append(item)
                await asyncio.sleep(0.005)

            await pool.mutate(operation)

        await asyncio.gather(*(mutate(item) for item in range(4)))
        assert preparation_peak == 2
        assert mutation_order == [0, 1, 2, 3]

    asyncio.run(run())


def test_qui_event_broker_supports_cursor_based_incremental_sync():
    broker = QuiEventBroker(limit=2)
    first = broker.publish("job.queued", "one", {"id": "one", "command": ["secret"]})
    broker.publish("job.running", "one", {"id": "one", "status": "running"})
    last = broker.publish("job.completed", "one", {"id": "one", "status": "completed"})
    cursor, events = broker.poll(first)
    assert cursor == last
    assert [event["type"] for event in events] == ["job.running", "job.completed"]
    assert all("command" not in event["job"] for event in events)


def test_qui_sync_blueprint_exposes_events_summary_and_bulk_retry():
    app = Flask(__name__)
    broker = QuiEventBroker()
    jobs = [{"id": "failed", "status": "failed"}, {"id": "active", "status": "running"}]
    retried: list[str] = []
    app.register_blueprint(
        create_qui_sync_blueprint(
            auth_check=lambda: (True, None),
            broker=broker,
            snapshots=lambda **_kwargs: jobs,
            retry_job=lambda job_id: not retried.append(job_id),
        )
    )
    broker.publish("job.running", "active", jobs[1])
    client = app.test_client()
    assert client.get("/api/qui/events?cursor=0").get_json()["events"][0]["type"] == "job.running"
    assert client.get("/api/qui/summary").get_json()["active"] == 1
    response = client.post("/api/qui/retry", json={})
    assert response.status_code == 202
    assert retried == ["failed"]


def test_runtime_api_blueprint_exposes_health_and_read_only_plans(tmp_path):
    class Limiter:
        @staticmethod
        def limit(*_args, **_kwargs):
            return lambda function: function

    source = tmp_path / "release.mkv"
    source.write_bytes(b"video")
    config = {"DEFAULT": {"screens": 1}, "TRACKERS": {"default_trackers": ["AITHER"]}}
    app = Flask(__name__)
    app.register_blueprint(
        create_runtime_api_blueprint(
            auth_check=lambda: (True, None),
            limiter=Limiter(),
            basic_rate_key=lambda: "test",
            rate_limit_key=lambda: "test",
            resolve_user_path=lambda value, **_kwargs: value,
            validate_args=lambda _value, _unattended: ([], ""),
            load_config=lambda _path: config,
            project_root=tmp_path,
        )
    )
    client = app.test_client()
    assert client.get("/api/health").get_json()["success"]
    assert "cache" in client.get("/api/runtime/health").get_json()
    plan = client.post("/api/plan", json={"path": str(source)}).get_json()["plan"]
    assert plan["path"] == str(source)
    assert plan["trackers"] == ["AITHER"]


def test_runtime_cli_flags_are_parsed(tmp_path):
    meta, _, _ = Args({"DEFAULT": {"screens": 1}}).parse(
        [str(tmp_path), "--plan", "--no-resume", "--prepare-only", "--queue-prepare-concurrency", "3"],
        Meta(),
    )
    assert meta.dry_run_plan
    assert meta.no_resume
    assert meta.prepare_only
    assert meta.queue_prepare_concurrency == 3


def test_dry_run_queue_resolution_does_not_write_queue_logs(tmp_path):
    async def run() -> None:
        media = tmp_path / "media"
        media.mkdir()
        (media / "one.mkv").write_bytes(b"one")
        meta = Meta(queue="batch", unattended=True)
        queue = await QueueManager.plan_queue(str(media), meta, [str(media)], str(tmp_path))
        assert queue == [str(media / "one.mkv")]
        assert not (tmp_path / "tmp" / "batch_queue.log").exists()

    asyncio.run(run())

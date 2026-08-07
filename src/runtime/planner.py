"""Read-only execution planning for CLI, Web UI, and external automation."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.runtime.artifacts import preparation_key

PIPELINE_SIGNATURE = "release-preparation-v1"
CORE_PREPARATION_STAGES = ("gather_initial_metadata", "prepare_release")


def preparation_pipeline_signature(extra_stage_names: Sequence[str] = ()) -> str:
    return f"{PIPELINE_SIGNATURE}:{','.join((*CORE_PREPARATION_STAGES, *extra_stage_names))}"


@dataclass(slots=True, frozen=True)
class PlannedStage:
    name: str
    estimated_work: str
    cache_hit: bool = False
    external_calls: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class ExecutionPlan:
    path: str
    trackers: tuple[str, ...]
    stages: tuple[PlannedStage, ...]
    estimated_api_calls: int
    resumable: bool
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "stages": [asdict(stage) for stage in self.stages]}


def selected_trackers(meta: Mapping[str, Any] | Any, config: Mapping[str, Any]) -> tuple[str, ...]:
    raw = meta.get("trackers") if hasattr(meta, "get") else None
    if not raw:
        tracker_config = config.get("TRACKERS", {}) if isinstance(config, Mapping) else {}
        raw = tracker_config.get("default_trackers", []) if isinstance(tracker_config, Mapping) else []
    if isinstance(raw, str):
        values = raw.split(",")
    elif isinstance(raw, Sequence):
        values = [str(item) for item in raw]
    else:
        values = []
    return tuple(dict.fromkeys(value.replace(" ", "").upper() for value in values if value.strip()))


async def build_execution_plan(context: Any, meta: Mapping[str, Any] | Any, path: str | Path) -> ExecutionPlan:
    source = Path(path).expanduser().resolve()
    trackers = selected_trackers(meta, context.config)
    warnings: list[str] = []
    if not source.exists():
        warnings.append("source path does not exist")
    pipeline_signature = preparation_pipeline_signature(tuple(str(stage.name) for stage in context.extensions.pipeline_stages))
    key = await asyncio.to_thread(preparation_key, source, meta, pipeline_signature) if source.exists() else "missing"
    artifact_hit = await context.artifacts.contains(key) if source.exists() else False
    gather_hit = await context.checkpoints.completed_snapshot(key, pipeline_signature, "gather_initial_metadata") if source.exists() else None
    prepare_hit = await context.checkpoints.completed_snapshot(key, pipeline_signature, "prepare_release") if source.exists() else None
    provider_calls = ("TMDb/TVDb/IMDb metadata", "image host")
    stages = (
        PlannedStage("restore_preparation_artifacts", "small", artifact_hit),
        PlannedStage("gather_initial_metadata", "medium", gather_hit is not None, provider_calls),
        PlannedStage("prepare_release", "high", prepare_hit is not None, ("tracker duplicate checks", "MediaInfo/FFmpeg")),
        PlannedStage("upload_trackers", "network", False, tuple(f"tracker:{tracker}" for tracker in trackers)),
        PlannedStage("inject_client", "small", False, ("torrent client",)),
    )
    estimated = sum(len(stage.external_calls) for stage in stages if not stage.cache_hit)
    return ExecutionPlan(str(source), trackers, stages, estimated, bool(gather_hit or prepare_hit), tuple(warnings))

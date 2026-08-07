"""Composable, observable upload pipeline primitives."""

from __future__ import annotations

import inspect
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from src.meta import Meta
from src.runtime.context import ExecutionContext


class StageStatus(StrEnum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    STOPPED = "stopped"


@dataclass(slots=True, frozen=True)
class StageResult:
    status: StageStatus = StageStatus.COMPLETED
    detail: str = ""

    @classmethod
    def completed(cls, detail: str = "") -> StageResult:
        return cls(StageStatus.COMPLETED, detail)

    @classmethod
    def skipped(cls, detail: str = "") -> StageResult:
        return cls(StageStatus.SKIPPED, detail)

    @classmethod
    def stopped(cls, detail: str = "") -> StageResult:
        return cls(StageStatus.STOPPED, detail)


class PipelineStage(Protocol):
    name: str

    async def run(self, context: ExecutionContext, meta: Meta) -> StageResult: ...


StageObserver = Callable[[str, StageResult, float], Awaitable[None] | None]


@dataclass(slots=True)
class Pipeline:
    stages: Sequence[PipelineStage]
    observers: list[StageObserver] = field(default_factory=list)

    async def run(self, context: ExecutionContext, meta: Meta) -> list[StageResult]:
        results: list[StageResult] = []
        for stage in self.stages:
            context.raise_if_cancelled()
            started = time.perf_counter()
            with context.metrics.measure(f"pipeline.stage.{stage.name}"):
                result = await stage.run(context, meta)
            elapsed = time.perf_counter() - started
            results.append(result)
            for observer in self.observers:
                observed = observer(stage.name, result, elapsed)
                if inspect.isawaitable(observed):
                    await observed
            if result.status is StageStatus.STOPPED:
                break
        return results


@dataclass(slots=True)
class FunctionStage:
    """Compatibility adapter for extracting one legacy function at a time."""

    name: str
    function: Callable[[ExecutionContext, Meta], Awaitable[StageResult]]

    async def run(self, context: ExecutionContext, meta: Meta) -> StageResult:
        return await self.function(context, meta)

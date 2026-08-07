"""Per-run dependency container shared by CLI and Web UI execution."""

from __future__ import annotations

import asyncio
import contextvars
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.extensions import ExtensionRegistry, load_extensions
from src.metadata_cache import MetadataCache, cache_for
from src.runtime.artifacts import ArtifactStore
from src.runtime.checkpoints import CheckpointStore
from src.runtime.http import HttpClientPool
from src.runtime.metrics import RuntimeMetrics
from src.runtime.scheduler import AdaptiveScheduler
from src.runtime.subprocesses import SubprocessManager

_CURRENT_CONTEXT: contextvars.ContextVar[ExecutionContext | None] = contextvars.ContextVar(
    "upload_assistant_execution_context",
    default=None,
)


@dataclass(slots=True)
class ExecutionContext:
    """Own resources and cancellation state for one upload execution."""

    base_dir: Path
    config: dict[str, Any]
    metrics: RuntimeMetrics = field(default_factory=RuntimeMetrics)
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    artifacts: ArtifactStore = field(init=False)
    checkpoints: CheckpointStore = field(init=False)
    extensions: ExtensionRegistry = field(init=False)
    http: HttpClientPool = field(init=False)
    scheduler: AdaptiveScheduler = field(init=False)
    subprocesses: SubprocessManager = field(init=False)
    _context_token: contextvars.Token[ExecutionContext | None] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.base_dir = self.base_dir.resolve()
        self.artifacts = ArtifactStore(self.base_dir, self.config)
        self.checkpoints = CheckpointStore(self.base_dir, self.config)
        self.extensions = load_extensions(self.base_dir, self.config)
        self.scheduler = AdaptiveScheduler(self.base_dir, self.config)
        self.http = HttpClientPool(self.metrics, self.scheduler)
        default = self.config.get("DEFAULT", {}) if isinstance(self.config, dict) else {}
        try:
            concurrency = int(default.get("subprocess_concurrency", 4)) if isinstance(default, dict) else 4
        except (TypeError, ValueError):
            concurrency = 4
        self.subprocesses = SubprocessManager(concurrency, self.metrics)

    @classmethod
    def create(
        cls,
        base_dir: str | Path,
        config: dict[str, Any],
        *,
        metrics_enabled: bool = False,
    ) -> ExecutionContext:
        return cls(Path(base_dir), config, RuntimeMetrics(enabled=metrics_enabled))

    @property
    def cache(self) -> MetadataCache:
        return cache_for(self.base_dir, self.config)

    def cancel(self) -> None:
        self.cancelled.set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled.is_set():
            raise asyncio.CancelledError

    async def close(self) -> None:
        await self.subprocesses.close()
        await self.http.close()
        await self.scheduler.close()

    async def __aenter__(self) -> ExecutionContext:
        self._context_token = _CURRENT_CONTEXT.set(self)
        return self

    async def __aexit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        try:
            await self.close()
        finally:
            if self._context_token is not None:
                _CURRENT_CONTEXT.reset(self._context_token)
                self._context_token = None


def current_execution_context() -> ExecutionContext | None:
    """Return the context owned by the current async task, when available."""
    return _CURRENT_CONTEXT.get()

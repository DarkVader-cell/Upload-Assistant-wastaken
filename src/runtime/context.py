"""Per-run dependency container shared by CLI and Web UI execution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.metadata_cache import MetadataCache, cache_for
from src.runtime.http import HttpClientPool
from src.runtime.metrics import RuntimeMetrics


@dataclass(slots=True)
class ExecutionContext:
    """Own resources and cancellation state for one upload execution."""

    base_dir: Path
    config: dict[str, Any]
    metrics: RuntimeMetrics = field(default_factory=RuntimeMetrics)
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    http: HttpClientPool = field(init=False)

    def __post_init__(self) -> None:
        self.base_dir = self.base_dir.resolve()
        self.http = HttpClientPool(self.metrics)

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
        await self.http.close()

    async def __aenter__(self) -> ExecutionContext:
        return self

    async def __aexit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        await self.close()

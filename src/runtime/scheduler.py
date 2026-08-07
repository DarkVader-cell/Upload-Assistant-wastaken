"""Latency- and rate-limit-aware scheduling for providers and trackers."""

from __future__ import annotations

import asyncio
import contextlib
import email.utils
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from src.runtime.state import atomic_write_json, default_config, read_json

T = TypeVar("T")


@dataclass(slots=True)
class ProviderStats:
    requests: int = 0
    successes: int = 0
    failures: int = 0
    total_latency: float = 0.0
    last_latency: float = 0.0
    last_status: int | None = None
    cooldown_until: float = 0.0
    rate_remaining: int | None = None
    updated_at: float = 0.0

    @property
    def average_latency(self) -> float:
        return self.total_latency / self.requests if self.requests else 0.0

    @property
    def score(self) -> float:
        failure_penalty = self.failures / self.requests if self.requests else 0.0
        return self.average_latency + failure_penalty * 10.0 + (30.0 if self.cooldown_until > time.time() else 0.0)


class AdaptiveScheduler:
    """Bound concurrency, serialize same-provider mutations, and learn ordering."""

    def __init__(self, base_dir: str | Path, config: Mapping[str, Any] | None = None) -> None:
        settings = default_config(config)
        self.enabled = bool(settings.get("adaptive_scheduler_enabled", True))
        try:
            concurrency = max(1, int(settings.get("adaptive_scheduler_concurrency", 4)))
        except (TypeError, ValueError):
            concurrency = 4
        configured = Path(str(settings.get("adaptive_scheduler_state", "data/cache/runtime/scheduler.json")))
        base = Path(base_dir).resolve()
        self.path = configured if configured.is_absolute() else base / configured
        self._semaphore = asyncio.Semaphore(concurrency)
        self._mutation_locks: dict[str, asyncio.Lock] = {}
        self._stats = self._load()
        self._dirty = False

    def _load(self) -> dict[str, ProviderStats]:
        raw = read_json(self.path)
        providers = raw.get("providers", {}) if isinstance(raw, dict) else {}
        result: dict[str, ProviderStats] = {}
        if isinstance(providers, dict):
            for name, value in providers.items():
                if not isinstance(value, dict):
                    continue
                allowed = {key: value[key] for key in ProviderStats.__dataclass_fields__ if key in value}
                try:
                    result[str(name)] = ProviderStats(**allowed)
                except (TypeError, ValueError):
                    continue
        return result

    @staticmethod
    def _retry_after(headers: Mapping[str, str] | None) -> float:
        if not headers:
            return 0.0
        raw = headers.get("retry-after") or headers.get("Retry-After")
        if not raw:
            return 0.0
        try:
            return max(0.0, float(raw))
        except ValueError:
            try:
                parsed = email.utils.parsedate_to_datetime(raw)
                return max(0.0, parsed.timestamp() - datetime.now(UTC).timestamp())
            except (TypeError, ValueError):
                return 0.0

    def ordered(self, providers: Sequence[str]) -> list[str]:
        return sorted(providers, key=lambda name: self._stats.get(name, ProviderStats()).score)

    async def wait_ready(self, provider: str) -> None:
        if not self.enabled:
            return
        delay = self._stats.get(provider, ProviderStats()).cooldown_until - time.time()
        if delay > 0:
            await asyncio.sleep(min(delay, 300.0))

    def record(self, provider: str, elapsed: float, *, success: bool, status: int | None = None, headers: Mapping[str, str] | None = None) -> None:
        stats = self._stats.setdefault(provider, ProviderStats())
        stats.requests += 1
        stats.successes += int(success)
        stats.failures += int(not success)
        stats.total_latency += max(0.0, elapsed)
        stats.last_latency = max(0.0, elapsed)
        stats.last_status = status
        stats.updated_at = time.time()
        retry_after = self._retry_after(headers)
        if retry_after:
            stats.cooldown_until = max(stats.cooldown_until, time.time() + retry_after)
        if headers:
            remaining = headers.get("x-ratelimit-remaining") or headers.get("ratelimit-remaining")
            with contextlib.suppress(TypeError, ValueError):
                stats.rate_remaining = int(remaining) if remaining is not None else stats.rate_remaining
            if stats.rate_remaining == 0 and not retry_after:
                stats.cooldown_until = max(stats.cooldown_until, time.time() + 5.0)
        self._dirty = True

    async def run(self, provider: str, operation: Callable[[], Awaitable[T]], *, serialize_mutation: bool = False) -> T:
        if not self.enabled:
            return await operation()
        await self.wait_ready(provider)
        lock = self._mutation_locks.setdefault(provider, asyncio.Lock()) if serialize_mutation else _NullAsyncLock()
        async with self._semaphore, lock:
            started = time.perf_counter()
            try:
                value = await operation()
            except BaseException:
                self.record(provider, time.perf_counter() - started, success=False)
                raise
            self.record(provider, time.perf_counter() - started, success=True)
            return value

    def snapshot(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "providers": {
                name: {**asdict(stats), "average_latency": stats.average_latency, "healthy": stats.cooldown_until <= time.time()}
                for name, stats in sorted(self._stats.items())
            },
        }

    async def close(self) -> None:
        if self._dirty:
            await asyncio.to_thread(atomic_write_json, self.path, self.snapshot())
            self._dirty = False


class _NullAsyncLock:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        return None

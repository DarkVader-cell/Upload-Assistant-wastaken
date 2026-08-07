"""Low-overhead execution metrics used by benchmarks and diagnostics."""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Lock


@dataclass(slots=True)
class RuntimeMetrics:
    """Collect counters and elapsed timings without exposing user data."""

    enabled: bool = False
    counters: Counter[str] = field(default_factory=Counter)
    timings: dict[str, list[float]] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def increment(self, name: str, amount: int = 1) -> None:
        if not self.enabled:
            return
        with self._lock:
            self.counters[name] += amount

    def record(self, name: str, elapsed: float) -> None:
        if not self.enabled:
            return
        with self._lock:
            self.timings.setdefault(name, []).append(elapsed)

    @contextmanager
    def measure(self, name: str) -> Iterator[None]:
        if not self.enabled:
            yield
            return
        started = time.perf_counter()
        try:
            yield
        finally:
            self.record(name, time.perf_counter() - started)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "counters": dict(self.counters),
                "timings": {name: list(values) for name, values in self.timings.items()},
            }

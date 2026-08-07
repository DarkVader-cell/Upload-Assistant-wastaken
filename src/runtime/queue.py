"""Bounded preparation concurrency with explicit prompt/mutation gates."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field


@dataclass(slots=True)
class SafeParallelPreparation[T, R]:
    concurrency: int = 2
    prompt_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    mutation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def prepare(self, items: Sequence[T], operation: Callable[[T], Awaitable[R]]) -> list[R | BaseException]:
        semaphore = asyncio.Semaphore(max(1, self.concurrency))

        async def one(item: T) -> R:
            async with semaphore:
                return await operation(item)

        return await asyncio.gather(*(one(item) for item in items), return_exceptions=True)

    async def prompt(self, operation: Callable[[], Awaitable[R]]) -> R:
        async with self.prompt_lock:
            return await operation()

    async def mutate(self, operation: Callable[[], Awaitable[R]]) -> R:
        async with self.mutation_lock:
            return await operation()

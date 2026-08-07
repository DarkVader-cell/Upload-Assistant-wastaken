"""Reusable HTTP sessions and in-flight request coalescing."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, TypeVar

import httpx

from src.runtime.metrics import RuntimeMetrics

T = TypeVar("T")


def _stable_mapping(value: Mapping[str, str] | None) -> str:
    if not value:
        return ""
    return json.dumps(sorted((str(key).lower(), str(item)) for key, item in value.items()))


class HttpClientPool:
    """Own and reuse compatible ``httpx.AsyncClient`` instances per execution."""

    def __init__(self, metrics: RuntimeMetrics | None = None) -> None:
        self.metrics = metrics or RuntimeMetrics()
        self._clients: dict[tuple[object, ...], httpx.AsyncClient] = {}
        self._inflight: dict[str, asyncio.Task[Any]] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    async def client(
        self,
        name: str,
        *,
        request_timeout: float | httpx.Timeout = 30.0,
        headers: Mapping[str, str] | None = None,
        follow_redirects: bool = False,
        verify: bool = True,
    ) -> httpx.AsyncClient:
        """Return a pooled client for a stable provider/configuration tuple."""
        if self._closed:
            raise RuntimeError("HTTP client pool is closed")
        timeout_config = httpx.Timeout(request_timeout)
        key = (
            name,
            timeout_config.connect,
            timeout_config.read,
            timeout_config.write,
            timeout_config.pool,
            _stable_mapping(headers),
            follow_redirects,
            verify,
        )
        async with self._lock:
            client = self._clients.get(key)
            if client is None:
                client = httpx.AsyncClient(
                    timeout=timeout_config,
                    headers=dict(headers or {}),
                    follow_redirects=follow_redirects,
                    verify=verify,
                )
                self._clients[key] = client
                self.metrics.increment("http.clients.created")
            else:
                self.metrics.increment("http.clients.reused")
            return client

    async def coalesce(self, key: str, operation: Callable[[], Awaitable[T]]) -> T:
        """Share one in-flight operation between callers using the same safe key."""
        if self._closed:
            raise RuntimeError("HTTP client pool is closed")
        async with self._lock:
            task = self._inflight.get(key)
            if task is None:
                task = asyncio.create_task(operation())
                self._inflight[key] = task
                self.metrics.increment("http.operations.started")
            else:
                self.metrics.increment("http.operations.coalesced")
        try:
            return await asyncio.shield(task)
        finally:
            if task.done():
                async with self._lock:
                    if self._inflight.get(key) is task:
                        self._inflight.pop(key, None)

    async def close(self) -> None:
        """Cancel owned in-flight work and close every pooled connection."""
        if self._closed:
            return
        self._closed = True
        async with self._lock:
            tasks = list(self._inflight.values())
            clients = list(self._clients.values())
            self._inflight.clear()
            self._clients.clear()
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if clients:
            await asyncio.gather(*(client.aclose() for client in clients), return_exceptions=True)

    async def __aenter__(self) -> HttpClientPool:
        return self

    async def __aexit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        await self.close()

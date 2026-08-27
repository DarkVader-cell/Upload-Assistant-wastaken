"""Reusable HTTP sessions and in-flight request coalescing."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, TypeVar

import httpx

from src.runtime.metrics import RuntimeMetrics

if TYPE_CHECKING:
    from src.runtime.scheduler import AdaptiveScheduler

T = TypeVar("T")


def _stable_mapping(value: Mapping[str, str] | None) -> str:
    if not value:
        return ""
    return json.dumps(sorted((str(key).lower(), str(item)) for key, item in value.items()))


class HttpClientPool:
    """Own and reuse compatible ``httpx.AsyncClient`` instances per execution."""

    def __init__(self, metrics: RuntimeMetrics | None = None, scheduler: AdaptiveScheduler | None = None) -> None:
        self.metrics = metrics or RuntimeMetrics()
        self.scheduler = scheduler
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
            if self._closed:
                raise RuntimeError("HTTP client pool is closed")
            client = self._clients.get(key)
            if client is None:
                async def request_started(request: httpx.Request) -> None:
                    if self.scheduler is not None:
                        await self.scheduler.wait_ready(name)
                    request.extensions["ua_started_at"] = time.perf_counter()

                async def response_received(response: httpx.Response) -> None:
                    if self.scheduler is None:
                        return
                    started = response.request.extensions.get("ua_started_at")
                    elapsed = time.perf_counter() - float(started) if isinstance(started, int | float) else 0.0
                    self.scheduler.record(
                        name,
                        elapsed,
                        success=response.is_success,
                        status=response.status_code,
                        headers=response.headers,
                    )

                client = httpx.AsyncClient(
                    timeout=timeout_config,
                    headers=dict(headers or {}),
                    follow_redirects=follow_redirects,
                    verify=verify,
                    event_hooks={"request": [request_started], "response": [response_received]},
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
            if self._closed:
                raise RuntimeError("HTTP client pool is closed")
            task = self._inflight.get(key)
            if task is None:
                task = asyncio.create_task(operation())
                self._inflight[key] = task
                task.add_done_callback(lambda completed, operation_key=key: self._discard_completed(operation_key, completed))
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

    def _discard_completed(self, key: str, task: asyncio.Task[Any]) -> None:
        """Release completed work even when every caller was cancelled.

        ``coalesce`` shields its shared task from caller cancellation. Without
        this callback, a cancelled caller is the only code path that may remove
        a completed task from ``_inflight``, retaining provider results and
        exceptions for the lifetime of a long-running Web UI execution.
        """
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


@asynccontextmanager
async def shared_http_client(
    name: str,
    *,
    request_timeout: float | httpx.Timeout = 30.0,
    headers: Mapping[str, str] | None = None,
    follow_redirects: bool = False,
    verify: bool = True,
    factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
) -> AsyncIterator[httpx.AsyncClient]:
    """Use the active execution pool, with an owned-client compatibility fallback."""
    from src.runtime.context import current_execution_context

    context = current_execution_context()
    if context is not None:
        yield await context.http.client(
            name,
            request_timeout=request_timeout,
            headers=headers,
            follow_redirects=follow_redirects,
            verify=verify,
        )
        return

    async with factory(
        timeout=request_timeout,
        headers=dict(headers or {}),
        follow_redirects=follow_redirects,
        verify=verify,
    ) as client:
        yield client

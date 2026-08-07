"""Owned, bounded async subprocess execution."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from src.runtime.metrics import RuntimeMetrics


@dataclass(slots=True, frozen=True)
class ProcessResult:
    args: tuple[str, ...]
    returncode: int
    stdout: bytes
    stderr: bytes


class SubprocessManager:
    """Run and clean up only subprocesses owned by one upload execution."""

    def __init__(self, concurrency: int = 4, metrics: RuntimeMetrics | None = None) -> None:
        self.metrics = metrics or RuntimeMetrics()
        self._semaphore = asyncio.Semaphore(max(1, concurrency))
        self._processes: set[asyncio.subprocess.Process] = set()
        self._lock = asyncio.Lock()
        self._closed = False

    async def run(
        self,
        args: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
        stderr_to_stdout: bool = False,
    ) -> ProcessResult:
        if self._closed:
            raise RuntimeError("subprocess manager is closed")
        command = tuple(str(arg) for arg in args)
        if not command:
            raise ValueError("subprocess command cannot be empty")
        async with self._semaphore:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(cwd) if cwd is not None else None,
                env=dict(env) if env is not None else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT if stderr_to_stdout else asyncio.subprocess.PIPE,
            )
            async with self._lock:
                self._processes.add(process)
            self.metrics.increment("subprocess.started")
            try:
                if timeout_seconds is None:
                    stdout, stderr = await process.communicate()
                else:
                    async with asyncio.timeout(timeout_seconds):
                        stdout, stderr = await process.communicate()
            except (TimeoutError, asyncio.CancelledError):
                await self._terminate(process)
                self.metrics.increment("subprocess.terminated")
                raise
            finally:
                async with self._lock:
                    self._processes.discard(process)
            self.metrics.increment("subprocess.completed")
            return ProcessResult(command, int(process.returncode or 0), stdout or b"", stderr or b"")

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        try:
            process.terminate()
        except ProcessLookupError:
            return
        try:
            async with asyncio.timeout(3):
                await process.wait()
        except TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                return
            await process.wait()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        async with self._lock:
            processes = list(self._processes)
        if processes:
            await asyncio.gather(*(self._terminate(process) for process in processes), return_exceptions=True)
        async with self._lock:
            self._processes.clear()


async def run_shared_subprocess(
    args: Sequence[str],
    *,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float | None = None,
    stderr_to_stdout: bool = False,
) -> ProcessResult:
    """Use the current execution manager, or a short-lived compatibility manager."""
    from src.runtime.context import current_execution_context

    context = current_execution_context()
    if context is not None:
        return await context.subprocesses.run(
            args,
            cwd=cwd,
            env=env,
            timeout_seconds=timeout_seconds,
            stderr_to_stdout=stderr_to_stdout,
        )
    manager = SubprocessManager(concurrency=1)
    try:
        return await manager.run(
            args,
            cwd=cwd,
            env=env,
            timeout_seconds=timeout_seconds,
            stderr_to_stdout=stderr_to_stdout,
        )
    finally:
        await manager.close()

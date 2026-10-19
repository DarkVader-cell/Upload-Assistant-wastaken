"""Bounded retries for explicitly read-only tracker work, never upload replays."""

from __future__ import annotations

import asyncio
import secrets
import ssl
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from src.console import logger

RETRY_STATUS = frozenset({408, 429, 500, 502, 503, 504, 520, 522, 523, 524})


class TrackerReadError(RuntimeError):
    """Read failed without establishing vacancy; safe message contains no URL/key."""


def error_kind(exc: Exception) -> str:
    if certificate_error(exc):
        return "TLS certificate verification failed"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__


def certificate_error(exc: BaseException) -> bool:
    current: BaseException | None = exc
    for _ in range(10):
        if current is None:
            break
        if isinstance(current, ssl.SSLCertVerificationError):
            return True
        if "certificate verify failed" in str(current).casefold():
            return True
        current = current.__cause__ or current.__context__
    return False


def retryable_read(exc: Exception) -> bool:
    if certificate_error(exc):
        return False
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRY_STATUS
    return isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError, httpx.ProxyError))


def safe_upload_retry(exc: Exception) -> bool:
    """Only errors before any request body can have reached the tracker."""
    return isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)) and not certificate_error(exc)


def request_cause(exc: Exception) -> Exception | None:
    current: BaseException | None = exc
    for _ in range(10):
        if isinstance(current, (httpx.RequestError, httpx.HTTPStatusError)):
            return current
        if current is None:
            return None
        current = current.__cause__
    return None


def retry_after(exc: Exception) -> float | None:
    if not isinstance(exc, httpx.HTTPStatusError):
        return None
    value = exc.response.headers.get("retry-after")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                return None
            return max(0.0, (when - datetime.now(UTC)).total_seconds())
        except ValueError, TypeError, OverflowError:
            return None


async def retry_readonly[T](operation: Callable[[], Awaitable[T]], tracker: str, *, operation_name: str = "duplicate search", attempts: int = 3) -> T:
    """Caller must guarantee this operation cannot submit a torrent/report.

    Auth/validation/certificate failures do not retry. Long Retry-After delays
    are not shortened: defer instead of retrying early. Cancellation propagates.
    """
    attempts = max(1, min(3, attempts))
    for attempt in range(attempts):
        try:
            return await operation()
        except Exception as error:
            exc = request_cause(error)
            if exc is None:
                raise
            delay = retry_after(exc)
            if not retryable_read(exc) or attempt == attempts - 1 or (delay is not None and delay > 30):
                suffix = "; server requested a longer wait" if delay is not None and delay > 30 else ""
                raise TrackerReadError(f"{tracker}: {operation_name} failed ({error_kind(exc)}, {attempt + 1} attempt(s)){suffix}. No valid result was obtained.") from None
            wait = delay if delay is not None else 0.5 * (2**attempt) + (0.1 + secrets.randbelow(301) / 1000)
            logger.warning(f"{tracker}: transient {operation_name} failure ({error_kind(exc)}); retry {attempt + 2}/{attempts} in {wait:.1f}s.", extra={"markup": False})
            await asyncio.sleep(wait)
    raise AssertionError("retry loop exhausted unexpectedly")

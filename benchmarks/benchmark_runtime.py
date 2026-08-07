#!/usr/bin/env python3
"""Deterministic microbenchmarks for shared runtime and Web UI hot paths."""

# The script must add the repository root before importing local packages.
# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.meta import Meta
from src.metadata_cache import cache_for
from src.runtime.context import ExecutionContext
from src.runtime.http import HttpClientPool
from src.runtime.pipeline import FunctionStage, Pipeline, StageResult
from web_ui.browse_index import BrowseIndex


def median_seconds(operation: Callable[[], Any], repeats: int) -> float:
    samples: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        operation()
        samples.append(time.perf_counter() - started)
    return statistics.median(samples)


async def benchmark_http_pool(iterations: int) -> tuple[float, float]:
    started = time.perf_counter()
    for _ in range(iterations):
        client = httpx.AsyncClient()
        await client.aclose()
    unpooled = time.perf_counter() - started

    pool = HttpClientPool()
    started = time.perf_counter()
    for _ in range(iterations):
        await pool.client("benchmark")
    pooled = time.perf_counter() - started
    await pool.close()
    return unpooled, pooled


async def benchmark_pipeline(iterations: int, temp_root: Path) -> float:
    async def stage(_context: ExecutionContext, _meta: Meta) -> StageResult:
        return StageResult.completed()

    pipeline = Pipeline([FunctionStage("noop", stage)])
    context = ExecutionContext.create(temp_root, {})
    meta = Meta()
    started = time.perf_counter()
    for _ in range(iterations):
        await pipeline.run(context, meta)
    elapsed = time.perf_counter() - started
    await context.close()
    return elapsed


def benchmark_browse_index(temp_root: Path, file_count: int, repeats: int) -> tuple[float, float]:
    media_root = temp_root / "media"
    media_root.mkdir()
    for index in range(file_count):
        (media_root / f"Example.Release.{index:05}.mkv").touch()
    browse = BrowseIndex(temp_root / "browse.sqlite", refresh_seconds=3600)
    browse._start_watcher = lambda _roots: None  # type: ignore[method-assign]
    build_started = time.perf_counter()
    browse._refresh([str(media_root)])
    build_elapsed = time.perf_counter() - build_started
    query_elapsed = median_seconds(lambda: browse.search([str(media_root)], "Example Release", "all", 100), repeats)
    return build_elapsed, query_elapsed


def compare_baseline(results: dict[str, float], baseline_path: Path, max_regression: float) -> list[str]:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    for name, current in results.items():
        previous = baseline.get(name)
        if not isinstance(previous, int | float) or previous <= 0:
            continue
        regression = (current - float(previous)) / float(previous)
        if regression > max_regression:
            failures.append(f"{name}: {regression:.1%} slower than baseline")
    return failures


async def run(smoke: bool) -> dict[str, float]:
    repeats = 2 if smoke else 7
    iterations = 5 if smoke else 50
    file_count = 100 if smoke else 2000
    with tempfile.TemporaryDirectory(prefix="ua-benchmark-") as directory:
        temp_root = Path(directory)
        unpooled, pooled = await benchmark_http_pool(iterations)
        browse_build, browse_query = benchmark_browse_index(temp_root, file_count, repeats)
        cache_config = {"DEFAULT": {"metadata_cache_dir": "cache"}}
        cache_lookup = median_seconds(lambda: cache_for(temp_root, cache_config), repeats * 1000)
        pipeline = await benchmark_pipeline(iterations * 10, temp_root)
    return {
        "http_client_unpooled_seconds": unpooled,
        "http_client_pooled_seconds": pooled,
        "browse_index_build_seconds": browse_build,
        "browse_index_query_seconds": browse_query,
        "cache_facade_lookup_seconds": cache_lookup,
        "pipeline_noop_seconds": pipeline,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--max-regression", type=float, default=0.05)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    results = asyncio.run(run(args.smoke))
    rendered = json.dumps(results, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if args.baseline:
        failures = compare_baseline(results, args.baseline, args.max_regression)
        if failures:
            for failure in failures:
                print(failure)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

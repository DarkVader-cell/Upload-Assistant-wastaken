# Reliability, performance, and recovery

This is the concise operational reference for long-running CLI and Web UI use.
It complements the detailed [architecture](architecture.md), [workflow](workflow-improvements.md), [Web UI](web-ui-basic.md), and [configuration](configuration.md) guides.

## Resource ownership

Each upload execution owns its HTTP clients, subprocesses, scheduler state, artifacts, and checkpoints through `ExecutionContext`. Closing one execution releases only that execution's resources; it does not cancel unrelated Web UI requests or detached jobs. Legacy cleanup remains available for terminal recovery and performs broad task cancellation only during final application shutdown.

Provider requests with the same safe cache key are coalesced while in progress. Completed requests are released even if every waiting caller disconnects. External commands are concurrency-limited, receive timeout/cancellation cleanup, and cannot start after their execution context closes.

## Web UI recovery

The Operations UI persists detached jobs, marks in-flight work as `interrupted` after a restart, and never silently replays it. Progress events and regular output are handled separately so incomplete progress records do not become prompts. Superseded file-browser searches are cancelled in the browser; the server retains a bounded SQLite index and stops its filesystem watcher during shutdown or reload.

If a process cannot be terminated, its session remains visible and the API returns an error rather than falsely reporting success. Retry or cancel it from Operations after addressing the underlying process or client problem.

## Torrent-client failures

qBittorrent and Deluge profiles keep their existing configuration and path-mapping contracts. Connection, timeout, retry, SSL, authentication, and remote-path errors should be corrected in the affected profile rather than by removing the profile. The configuration editor repairs default, injecting, and searching references only when a profile is intentionally removed.

## Torrent and image-host metadata

New and reused-base torrents are stamped with `UA, Arty's fork` in both their comment and `created by` fields. Image-host requests use `DEFAULT["image_upload_timeout"]`, which defaults to 15 seconds and is bounded between 5 and 60 seconds; keep the value low enough for fallback hosts to remain responsive.

## Validation before publishing

Run the following from a Python 3.14 environment after source changes:

```bash
uv lock --check
uv run python -m compileall src web_ui upload.py config-generator.py
uv run ruff check .
uv run python scripts/architecture_guard.py
uv run python benchmarks/benchmark_runtime.py --smoke
uv run python -m pytest -q
git diff --check
```

For Docker-affecting changes, also run the repository's Docker validation or the corresponding GitHub workflow. The architecture guard prevents new direct async-client/subprocess coupling and Web UI monolith growth; the benchmark smoke test catches regressions in client pooling, runtime setup, cache lookup, pipeline execution, and browser indexing.

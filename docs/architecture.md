# Architecture and Upstream-Sync Boundaries

CLI and Web UI runs share an `ExecutionContext`, which owns HTTP connections, metadata-cache facades, subprocesses, cancellation, and optional metrics. Release preparation is moving into ordered `PipelineStage` implementations; compatibility adapters keep existing function signatures while stages are extracted.

Tracker classes remain importable from their historical modules. `TrackerRegistry` normalizes construction and capability lookup over the live legacy class map, allowing individual trackers to migrate without breaking callers or tests.

Fork-only behavior should live in new service or extension modules. Upstream-owned entrypoints should contain thin calls into those modules, not feature implementations. The scheduled upstream forecast identifies integration seams before the hourly `dev` sync is blocked; validated `dev` changes promote to `main` through a pull request.

Direct `httpx.AsyncClient` and `asyncio.create_subprocess_exec` use are migration debt. New code uses the shared runtime helpers, and the architecture guard prevents these counts or the Web UI monolith from growing.

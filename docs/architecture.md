# Architecture and Upstream-Sync Boundaries

CLI and Web UI runs share an `ExecutionContext`, which owns HTTP connections, metadata-cache facades, content-addressed artifacts, stage checkpoints, adaptive scheduling, subprocesses, cancellation, and optional metrics. Release preparation runs through ordered `PipelineStage` implementations; compatibility adapters keep existing function signatures while stages are extracted.

Tracker classes remain importable from their historical modules. `TrackerRegistry` normalizes construction and capability lookup over the live legacy class map, allowing individual trackers to migrate without breaking callers or tests.

The runtime writes generated state under configurable `data/cache` paths. Preparation manifests point to immutable SHA-256 objects, checkpoint files are written atomically, and both are keyed by the source signature plus preparation options. Pipeline signatures include extension stages, so changed code or extension order cannot silently resume incompatible work. A bounded WAL-mode SQLite store keeps a non-secret release projection shared by CLI, Web UI, and detached Qui processes; indexed status/time queries avoid loading the history into the Web UI process.

`src/extensions.py` is the stable fork boundary for third-party trackers, metadata providers, pipeline stages, and health checks. Extensions are disabled by default, cannot replace built-in tracker names, and may be loaded from the `upload_assistant.extensions` package entry-point group or explicitly configured local directories. See `docs/extensions.md` for the version 1 contract.

Unattended regular queues may prepare unique temporary workspaces concurrently. Interactive, site-upload, argument-line, or basename-colliding queues remain sequential. Tracker uploads and torrent-client mutations stay in the ordered upload phase.

Fork-only behavior should live in new service or extension modules. Upstream-owned entrypoints should contain thin calls into those modules, not feature implementations. The release-history and config-removal HTTP contracts are Flask blueprints under `web_ui/services`, keeping `web_ui/server.py` below its architecture ceiling. The scheduled upstream forecast identifies integration seams before the hourly `dev` sync is blocked; validated `dev` changes promote to `main` through a pull request.

Direct `httpx.AsyncClient` and `asyncio.create_subprocess_exec` use are migration debt. New code uses the shared runtime helpers, and the architecture guard prevents these counts or the Web UI monolith from growing.

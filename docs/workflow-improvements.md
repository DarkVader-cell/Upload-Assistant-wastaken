# Workflow, Performance, and Tracker Improvements

This guide describes the fork-specific workflow improvements that complement the existing Upload Assistant flow without replacing upstream behavior. Existing CLI arguments, tracker adapters, screenshot controls, client profiles, and queue modes remain available.

## Persistent release history

CLI uploads, interactive Web UI runs, and detached Qui jobs write a compact release projection to SQLite. The default database is `data/cache/release_history.sqlite3`; it uses WAL mode and indexed status/update-time queries so the Operations UI does not need to load the whole history into memory.

Configure it under `DEFAULT`:

```python
"release_history_enabled": True,
"release_history_db": "data/cache/release_history.sqlite3",
"release_history_max_entries": 5000,
```

The row limit is enforced after each update by pruning the oldest rows. Records contain release identity, source path, category/type/resolution, status, selected/successful/failed trackers, public external IDs, and an optional Qui job ID. CLI arguments, API keys, cookies, passkeys, passwords, tokens, and session secrets are not stored.

The authenticated `GET /api/release_history` endpoint accepts:

- `q`: case-insensitive text search across release name, source path, record ID, job ID, and tracker data; truncated to 200 characters;
- `status`: one of `cancelled`, `completed`, `debug`, `failed`, `interrupted`, `queued`, `running`, or `skipped`;
- `limit`: 1–500, default 100;
- `offset`: non-negative pagination offset.

Invalid filters return HTTP 400. A temporarily unavailable database returns HTTP 503. Disabling history produces an empty successful result rather than deleting existing records.

## Qui and unattended operations

Detached Qui submissions remain FIFO and persist in `tmp/qui_jobs.json`. Queued jobs can be edited or cancelled; failed/interrupted jobs can be retried; active prompts and metadata checkpoints can be answered through the Operations UI. Running jobs are never silently rewritten, and jobs found active after a restart become `interrupted` instead of being blindly replayed.

Release history complements the live queue: queue state controls current work, while history provides a bounded searchable record across restarts. Automation can use cursor events and compact summaries to avoid repeatedly downloading the full job list. See [Web UI API](web-ui-api.md) for endpoint contracts and [Qui Docker deployment](qui-docker-deployment.md) for persistent mounts.

## Safe torrent-client profile removal

The config editor can remove a configured `TORRENT_CLIENTS` profile. The server serializes the mutation and atomically replaces `data/config.py`. It also repairs references in `DEFAULT`:

- a removed `default_torrent_client` becomes the alphabetically first remaining profile, or is removed when no profiles remain;
- the profile is removed from `injecting_client_list` and `searching_client_list`;
- empty reference lists are removed;
- implementation values such as `qbit`, `deluge`, or `rtorrent` are not mistaken for profile names.

The operation is authenticated, requires CSRF/same-origin validation for browser sessions, and is recorded in `data/config_audit.log`. A mounted read-only config intentionally causes the operation to fail rather than partially update it.

## Screenshot delete and refill

Screenshot review retains the existing Delete and Replace actions and adds **Delete + refill**. Refill captures a fresh frame for the same logical slot while preserving its ID, index, ordering, and target screenshot count. This also works for pending remote additions, avoiding a delete/re-add cycle that would move the image to the end of the description.

Use plain Delete when fewer screenshots are intentional. Use Replace when the original slot should remain visibly present throughout review. Captures are staged before the review manifest is updated, so a failed capture does not publish a half-written replacement.

## Structured full-disc duplicate checks

Anthelion, HDBits, and AvistaZ-family adapters now project structured category, type, source, container, codec, group, and file-count evidence where their APIs expose it. Duplicate filtering recognizes full discs from tracker type/container fields before falling back to release-name markers.

For a full-disc upload, an explicitly non-disc candidate is excluded. An explicit full-disc candidate remains eligible even when a tracker reports one file or omits/mislabels encode-oriented resolution and HDR fields. Conversely, a structured full disc is not treated as a duplicate of a non-disc upload. Existing tracker-specific duplicate rules still run for candidates that remain comparable.

Valid standalone `BD_SUMMARY_*.txt` files are reused directly. Incomplete cached summaries are regenerated, while malformed full reports are skipped with an error instead of entering an unbounded retry loop.

## Tracker rule safeguards

### Blutopia (BLU)

The current BLU banned-group list is enforced case-insensitively. AOC, CMRG, EVO, TERMiNAL, and exact-name ViSION are raw-content exceptions, not general encode exceptions. Leading release-tag dashes are normalized before checking. AOC still requires explicit prior-approval confirmation for nominally raw WEB-DLs or discs; unattended runs without confirmation fail conservatively.

### DesiTorrents (DT)

The existing DT bans remain in place and the current YTS, RARBG, BonsaiHD, GalaxyRG, `-=!DrSTAR!=-`, AKG, and DUS entries are included. A listed-group WEB-DL is allowed only after an attended confirmation that it contains no advertisement tags or watermarks. Fully unattended runs remain blocked because MediaInfo cannot prove the absence of advertisements.

### Luminarr (LUME)

For non-disc `ENCODE` uploads:

- below 1080p requires x264;
- 1080p SDR live action requires x264;
- 1080p HDR, Dolby Vision, or HLG live action requires x265.

Animation at 1080p and non-encode uploads retain their existing behavior. The encoder is derived from prepared metadata and MediaInfo's encoded-library name when needed. These checks run before the remaining LUME preflight rules.

## Docker build and runtime

The Dockerfile separates Python dependencies and architecture-specific helper downloads from the final runtime stage. Requirements and binary-download inputs are copied before application source, allowing BuildKit to reuse expensive layers for source-only changes. Pip and apt caches use BuildKit cache mounts; compilers and download-only Python packages are absent from the final stage.

The build context excludes tests, documentation, Graphify data, host configuration, credentials, sessions, caches, logs, Node modules, and Windows-only binaries. The runtime image includes only the active architecture's helper binaries. If a mounted `data/` directory has no `config.py`, the entrypoint copies the bundled example on first start; an existing or read-only mounted config is never overwritten.

Persist `data/` to retain configuration, authentication state, caches, and release history. Persist `tmp/` when detached Qui queue/recovery state must survive recreation. Keep Docker layer caching enabled for normal builds; see [Docker](docker.md) for build and inspection commands.

## Upstream compatibility and verification

Fork-only services live in small runtime/Web UI modules and are registered through thin calls in upstream-owned entrypoints. Existing public signatures and feature paths are retained, and the architecture guard caps direct async-client creation, subprocess creation, and `web_ui/server.py` growth. Upstream sync remains a reviewed merge process; net dependency updates can be ported without retaining reverted intermediate refactors.

Recommended release checks are:

```bash
.venv/bin/python -m pytest -q
ruff check <changed Python files>
.venv/bin/python scripts/architecture_guard.py
git diff --check
```

For Docker-affecting changes, also build the image, run `--help`, and verify the container health check with persistent mounts.

# Dedicated-server catalogue dashboard

The new dashboard is **separate from Upload Assistant's existing Web UI**. It
runs the catalogue worker and CardinalDL commands on the dedicated server. It
needs no local computer or local Docker service to remain running.

**Security requirement: Tailscale-only. Never expose this dashboard through a
public nginx proxy or Tailscale Funnel.** Keep the application loopback-only.

## Supported controls

- Password login/logout, expiring HttpOnly/SameSite sessions, CSRF and Origin
  checks, login throttling, same-origin scripts, and no raw process logs.
- Country-of-production and original-language filters; configurable trackers and per-service regions. Use `ta, te, hi` for Tamil/Telugu/Hindi originals, or leave languages blank for any. Language is verified by exact IMDb/TMDB identity, not guessed from country or localized titles. Cardinal audio/subtitle preferences remain unchanged.
- Global/per-service UTC daily start limits, disk/age/time/check/page limits.
- Paginated/searchable/filterable persistent queue, per-status counts, immutable
  daily attempt counts, and recent activity. Lightweight status, bounded caches,
  adaptive polling, and hidden-tab suspension keep the UI responsive.
- Movie/TV selection, conservative absence/free-slot modes, and bounded episode
  expansion with per-episode deduplication and daily start accounting.
- Explicit queue rechecks; failed/uncertain payload retries require typed
  verification and never refund daily starts.
- Dry-run, explicit execution, queue-only mode, independent schedule pause, and
  cancellation of the worker owned by this dashboard. Cancel also pauses the
  schedule. It cannot signal an arbitrary PID supplied by a browser.
- Validated settings edits with timestamped private backups. Browser settings
  cannot change executable/config paths, credentials, or Cardinal profiles.
- An optional scheduler that is **disabled initially**, as are downloads.
- A non-download CLI health check (`--version`). This does **not** validate
  streaming-service authentication, proxy routing, provider IDs, or payloads.

See [catalogue-advanced.md](catalogue-advanced.md) for the metadata/profile bridge,
TV expansion, conservative UA slot decisions, migration, and recovery semantics.
Live API/download validation is still pending. REVIEW/trump/evidence requirements
never become unattended permissions; a slot finding is not upload approval.
Automatic provider failover, payload verification, tracker uploads, and DT
existing-title slot rules are not implemented.

## Installed layout

The intended dedicated deployment uses:

- Code: `~/apps/ua-catalogue/current` → a timestamped release directory.
- Existing Python environment: `~/apps/upload-assistant/.venv/bin/python`.
  No packages are installed into this production environment by this change.
- Private configuration: `~/.config/ua-catalogue/runner.json`.
- Salted password hash: `~/.config/ua-catalogue/auth.json` (no plaintext password).
- Persistent state: `~/.local/state/ua-catalogue/queue.sqlite3`.
- System service: `ua-catalogue.service`, running **as artemis, not root**, with
  `SupplementaryGroups=docker`; loopback listener `127.0.0.1:8777`.
- Private URL: `http://100.96.247.69:8777/` or
  `http://dedi.tail074c2.ts.net:8777/`, reachable only from the tailnet, with the
  dashboard password login. HTTP is carried inside the encrypted Tailscale link.
- Tailscale Serve TCP 8777 forwards to `127.0.0.1:8777`. No Funnel is enabled.
  The existing Upload Assistant TCP forwarding on 12348 is preserved.
- The former public `/catalogue/` path and its subpaths explicitly return 404;
  public TCP 8777 is unreachable.

At initial setup, the dashboard password can be bootstrapped from the existing
Cardinal Docker `REMOTE_ACCESS_PASSWORD` in memory, storing only a PBKDF2 hash.
It is the existing **Cardinal Web UI password**, not a tracker key. If that
password later changes, the dashboard hash must be explicitly updated; it is
not continuously synchronized. Never print environment variables or passwords.

Service template: `tools/ua-catalogue.service` (uses this dedicated host's explicit
paths; adapt them for another account). A user-service manager may retain stale
supplementary groups after Docker is installed. The system service explicitly
assigns the already-authorized Docker group without restarting the user manager.
Use `sudo systemctl status ua-catalogue.service` to inspect it.
`docs/catalogue-nginx.conf` is intentionally a **public deny rule**, not a proxy.
It is installed as `/etc/nginx/apps/ua-catalogue-deny-public.conf`. The former
public proxy was disabled and retained outside the active `*.conf` include.

Inspect and back up existing Serve configuration before adding this one port:

```bash
sudo tailscale serve status --json
sudo tailscale serve --bg --tcp=8777 tcp://127.0.0.1:8777
sudo tailscale serve status --json
```

Do not reset other Serve routes, enable Funnel, or open a WAN listener. Keep
`AllowFunnel` absent/false. Inspect targets and retain timestamped backups before
replacement; run `nginx -t` before any nginx reload. Do not restart Upload
Assistant, CardinalDL, qBittorrent, or active downloads for this dashboard.

## CardinalDL Docker adapter

The actual dedicated installation is `docker_compose-server-1`, with CLI
`/app/.output/src/cli.js` and database `/config/storage/storage.db` **inside the
container**. The host has no `cardinaldl` executable. Configure:

```json
{
  "cardinal_docker": {
    "container": "docker_compose-server-1",
    "user": "node",
    "workdir": "/app/.output",
    "cli": "src/cli.js"
  },
  "cardinal_configpath": "/config/storage/storage.db",
  "disk_path": "/home/artemis/docker_compose/cdl/downloads"
}
```

The adapter uses argument arrays and a small Node process supervisor. Docker
client signals alone do not reliably stop a container-side process. The
supervisor owns an isolated CLI child process group and terminates it on stdin
EOF or its internal timeout, without signalling the existing Cardinal server or
unrelated downloads. Both host and container-side guards are bounded. The
Cardinal profiles, proxy settings, mount layout, and running server are untouched.

Version 3.10.16, help flags, and the built-in language list were checked on the
dedicated container without calling streaming services. Amazon GTI support and
actual service access are separate integration checks still required before
unattended downloads. API testing can remain deferred: simply leave scheduling
and `allow_downloads` disabled. Merely opening the dashboard does not scan APIs.

## Testing

Worker, CLI, mock-API and browser tests run on the dedicated server. A separate
tailnet client also verifies private reachability, login/logout/CLI health, public
404 responses, and unreachable public TCP 8777:

```bash
cd ~/apps/ua-catalogue/current
~/apps/upload-assistant/.venv/bin/python -m pytest -q \
  tests/test_catalogue_*.py
```

The API tests are mocked. Real subprocess tests use temporary fake executables,
not actual media downloads. A separate optional Playwright smoke script,
`tests/catalogue_browser_smoke.py`, **refuses non-test URLs** and targets only
`127.0.0.1:8781`, using isolated test config/queue/auth. Its run buttons intercept
requests rather than calling real APIs. Browser dependencies live in a separate
test environment, not in Upload Assistant or the Cardinal container. Missing
Chromium NSS/NSPR libraries are unpacked under `~/apps/ua-catalogue/browser-libs`
for tests only (no system package installation). Set `LD_LIBRARY_PATH` to its
`root/usr/lib/x86_64-linux-gnu` directory when rerunning the browser fixture.
The queue uses SQLite JSON1 (available in the dedicated environment), bounded
SQL work selection, and indexed daily counters; it does not load the entire
pending catalogue into memory. Real-browser fixtures also cover pagination,
search, queue-recovery dialogs, persisted TV/slot settings, responsive layouts,
and screenshots. Their health response is synthetic; production CLI health
and offline installed-selector/rule tests are checked separately.

Keep live downloads disabled until catalogue/tracker API contracts, service IDs,
Cardinal profiles/proxies, and output paths have passed the later live validation.

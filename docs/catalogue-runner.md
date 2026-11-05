# Catalogue → tracker opportunities → CardinalDL

See [catalogue-dashboard.md](catalogue-dashboard.md) for the private dedicated
Web UI, and [catalogue-advanced.md](catalogue-advanced.md) for metadata, TV,
slot rules, profile snapshots, migration, and recovery details.

**Scheduling and downloads remain off until live API validation is approved.**
Offline tests do not verify provider IDs, account sessions, proxy regions, or
successful media acquisition. No tracker uploads are performed.

## Data flow

1. JustWatch GraphQL discovers subscription movies and optionally series per
   service availability region. `origin_countries` filters production countries,
   not the proxy/availability region. No HTML scraping or browser scraping.
2. Extract exact IMDb and provider identities from provider-owned offer URLs.
   Skip rentals, purchases, channel offers, missing identities, and ambiguous
   editions/IDs. Netflix IDs, Apple `umc.cmc` IDs, Amazon ASINs and GTIs are
   recognized. **Actual Amazon GTI acceptance remains a live validation gate.**
3. On the validated Docker path, Cardinal listing metadata verifies identity and
   its own saved preferences select the current manifest profile. A series
   expands into individually bounded, deduplicated episode jobs.
4. Reuse the existing trusted UA runtime config and API inventories/rules:
   HDB→HDBITS, PTP→PASSTHEPOPCORN, ATH→AITHER, DT→DESITORRENTS. HDB/PTP use
   IMDb; Aither/DT use exact IMDb→TMDB movie/TV mapping. Incomplete or failed
   inventories are unknown, never missing.
5. Apply `absent_all`, `missing_any`, or `missing_or_free_slot`. Evidence-required,
   ambiguous, review, and trump decisions cannot automatically qualify a slot.
6. On every execution attempt, obtain fresh evidence, check scope/age/disk/start
   limits, reserve a UTC daily start atomically, and call Cardinal with an argument
   array—not a shell. Existing Cardinal defaults remain authoritative; selected
   video/container/resolved languages are pinned per invocation, not saved back.

JustWatch's API is unofficial and may change, rate-limit, or restrict access.
Use it only where permitted; no access controls are bypassed. Schema failures
stop that page without advancing its cursor. Catalogue availability is not
proof of entitlement. An upload opportunity is not upload approval.

## Dedicated setup

Use the dedicated UA Python environment (`httpx` is already a dependency). Copy
`docs/catalogue-runner.example.json` outside git, replace the example paths, and
keep it private:

```bash
mkdir -m 700 -p ~/.config/ua-catalogue
cp docs/catalogue-runner.example.json ~/.config/ua-catalogue/runner.json
chmod 600 ~/.config/ua-catalogue/runner.json
```

The UA Python config is trusted executable local code, just as for UA itself.
Use its actual runtime `UA_DATA_DIR` config, not a checkout placeholder. Do not
copy credentials into the runner JSON. Cardinal must already be signed in.

The dedicated Docker adapter uses `verify_cardinal: true` and private mapped
metadata exchange paths; see [advanced setup](catalogue-advanced.md#dedicated-configuration).
Advanced workflows require that adapter. The native-binary movie-only absence
path remains for compatibility, without automatic Cardinal metadata comparison.

Default availability regions are Amazon **GB**, Netflix **US**, Apple TV **US**.
Cardinal's existing proxy profiles must match: changing a dashboard region does
not rewrite them. Unknown offer domains are skipped, not guessed.

Use one runner/state directory per Cardinal installation. The private state
directory must be mode 0700. `disk_path` must cover the real output filesystem;
monitor separate temporary/output filesystems separately. The worker does not
coordinate unrelated GUI downloads or change Cardinal's output folders.

## Validation, execution, and scheduling

Only after approval for live read-only requests:

```bash
python tools/catalogue-runner.py --config ~/.config/ua-catalogue/runner.json
```

This contacts catalogue/tracker APIs and, on the metadata-verified path, Cardinal
listing/manifest APIs. It writes local planning state but does not start media
downloads. Validate identity, availability, proxies, and one real ID per service,
especially Amazon GTIs. Never substitute a guessed ASIN for a failed GTI.

After live validation and explicit execution approval, set `allow_downloads`
and add `--execute`:

```bash
python tools/catalogue-runner.py --config ~/.config/ua-catalogue/runner.json --execute
```

The dashboard scheduler is separately opt-in. Nothing automatically installs a
cron job. A filesystem lock serializes dashboard and standalone workers using
the same state. `--queue-only` skips discovery, not fresh execution evidence.

## Limits and recovery

- Global/service daily limits count **starts per UTC day**, including failed or
  uncertain starts. Zero prevents starts. Each episode consumes one start;
  series discovery consumes none. The immutable ledger survives verified retry.
- `max_downloads_per_run` and `max_checks_per_run` bound work. Tracker calls are
  paced per API host. Series expansion has additional independent bounds.
- Cursors and candidates commit together. Exhaustion starts another traversal;
  changing popularity makes discovery best-effort, not a static snapshot.
- `min_free_gib` is a pre-launch floor, not a byte quota or size estimate.
- `max_candidate_age_hours` and region/origin/media scopes prevent stale or
  wrong-scope jobs executing. Rediscovery refreshes unstarted candidates.
- Unknown results back off; rediscovery does not erase that cooldown. Changing
  rules invalidates only unstarted planning evidence.
- Movie/episode keys deduplicate across providers. One candidate is retained at
  a time; there is no automatic provider failover after a started/failed download.
- Timeouts/cancellation stop owned processes, mark uncertainty, and stop further
  launches in that run. No partial media is deleted. Started/failed/uncertain/
  successful payload jobs never automatically replay.
- The UI's explicit recovery action requires verification for failed/uncertain
  payload retries. It never refunds starts. Never delete the state database to
  clear a limit. Legacy migration retains `jobs_v1_backup` transactionally.
- `succeeded` records CLI exit zero, **not independently verified media**. Raw
  CLI output is discarded to avoid storing tokens or private playback URLs.

## Remaining live integration gates

Account/region/proxy and provider-ID compatibility, real tracker inventory
responses, actual manifest/profile contracts, and a separately authorized
bounded download still need live validation. Offline metadata/slot tests use
synthetic inputs against the installed selector/rule libraries. DT existing-title
slots remain unsupported; title absence is conservative. Automatic trumping,
tracker uploads, payload verification, and notifications are outside this worker.

Run catalogue tests on the dedicated host:

```bash
python -m pytest -q tests/test_catalogue_*.py
```

Tests mock network APIs and download executors; browser fixtures explicitly
forbid real worker launches. Existing UA/Cardinal/qB services, queues, payloads,
credentials, and Cardinal profiles are not changed by tests.

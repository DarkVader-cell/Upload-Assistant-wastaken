# Metadata-verified catalogue workflows

> Deployment is private to Tailscale. Keep scheduling and downloads **off** until
> live provider/tracker API validation is explicitly approved. Offline tests do
> not establish that an account, provider ID, proxy region, or download works.

## Eligibility modes

- `absent_all`: every **applicable** selected tracker must confirm absence.
- `missing_any`: at least one applicable tracker must confirm absence.
- `missing_or_free_slot`: confirmed absence or an explicit UA slot-rule `ALLOW`
  without evidence requirements or a trump recommendation.

Unknown, incomplete, capped, ambiguous, failed, or review-required responses
never count as absence or a free slot. A verified opportunity on one tracker
can qualify the latter two modes despite unknown results elsewhere; those
unknown results are not promoted to absence.

The bridge reuses the installed Upload Assistant's API inventory adapters and
slot rules. HDB requests are exact-IMDb API searches. Full inventories include
pending results where the installed adapter supports them. Responses and
credentials are not exported to the browser. Tracker HTTP requests are paced,
HTTPS-origin restricted, and do not automatically follow arbitrary redirects.
PTP's same-site `torrents.php?id=<numeric group>` or exact-same-IMDb
`searchstr=tt...` redirect is the sole exception. Search redirects are accepted
only when they match the original request's IMDb exactly; broad/different-title
searches are rejected. The target is forced to `json=1`, separately paced, and
limited to one hop.
Login pages, cross-site targets, HTTP downgrades, extra/token query fields,
redirect loops, and HTML responses remain unknown rather than absence.

Catalogue API workers share a private, credential-free SQLite pacing ledger
across subprocesses: by default at least **10 seconds per host** and at most
**200 requests per host per UTC day**. These are conservative local budgets,
not a claim about each tracker's published/account-specific quota. Configure
stricter values where required. HTTP 429/503, `Retry-After`, exhausted
rate-limit/reset headers, and recognized HTTP-200 JSON throttling responses
create persistent cooldowns; they never trigger an immediate retry loop.
Independent non-catalogue applications are not controlled by this ledger.

PTP general episodes are not applicable. DT is considered only for known
applicable South Asian audio; unknown audio requires review. DT has no UA slot
evaluator, so only confirmed title absence can qualify it. HDB TV/signup and
other policy/evidence restrictions remain conservative review decisions.

**A slot finding is a preparation hint, not permission to upload.** This worker
never uploads, trumps, bypasses staff approval, or supplies missing evidence.

## Existing Cardinal profiles, not a second quality configuration

The metadata adapter loads Cardinal's saved preferences and calls its actual
quality selector on the current manifest. It checks the exact provider identity
and matches IMDb when supplied; otherwise native provider ID, title, and available
year must agree. Ambiguity is blocked, not guessed.

The invocation pins the selected video quality, HDR/hybrid choice, output
container, and resolved audio/subtitle languages. Other GUI defaults—including
proxies, output folders, naming, and audio codec preferences—remain Cardinal's
own settings. No Cardinal application files or saved profiles are modified.
Do not change those external settings during an active job.

A provider that supplies no playable full-title offer is shown as **unavailable**,
not missing or a valid download. In particular, Amazon's “No matching Playback
Envelope” failure can occur even when login and title lookup work. It requires
checking actual account/profile/regional availability or upstream compatibility;
no entitlement, trailer, or title-identity check is bypassed. Only a fixed error
code reaches the queue—never raw envelopes, tokens, or playback URLs.

The read-only adapter is pinned to Cardinal CLI 3.10.16, SHA256:

```
1963e0217e5dde2593312ba2b61fca089568c613a099d706a0f91ae8b7b3eeba
```

A changed build stops metadata verification until its adapter is validated.
Never bypass the pin to make an untested update run. The offline `--self-test`
uses synthetic tracks and prohibits networking.

Metadata exchanges contain only whitelisted fields, not manifests, signed
URLs, service tokens, or account settings. A private, user-owned, non-symlink
host directory must map to the same container directory. Files use unpredictable
names and are removed after their own request; no media cleanup occurs.

## TV and episode budgets

Catalogue selection supports release-year and IMDb-vote ranges, reported-runtime
bounds, literal title exclusions, discovery depth, and low-vote/oldest/recent/
catalogue ordering. **Year and vote bounds are sent to the catalogue API**, not
merely applied to the first page of popular titles; local validation remains as
a second check. An optional start offset browses deeper into the filtered pool.
### Original-language discovery

The **Original language(s)** field accepts comma-separated lowercase codes, for
example `ta, te, hi` (Tamil, Telugu, Hindi). Blank means any language; multiple
codes match **any** selected original language. Country remains an independent
filter. This does not change saved Cardinal audio/subtitle preferences and does
not mean dubbed-audio availability.

Original language is verified through the existing UA TMDB API using the exact
IMDb movie/series identity. JustWatch's metadata-localization `language` argument
is **not** used as a language filter. Unresolved or ambiguous language blocks
provider/manifest/download requests. Known nonmatches are excluded before queue
ranking, while unresolved candidates are checked within the existing per-run
budget; sparse matches may require more bounded catalogue pages/runs. Verified
language facts survive rediscovery. Changing selected languages gives discovery
its own cursor scope and invalidates only unstarted evidence under the worker
lock. In strict movie absence mode, a first selected-tracker hit still stops
before language/provider calls.

Each criteria combination owns its own persistent cursor. The API's numeric
cursor is decoded to an absolute offset for subsequent pages; relying on `after`
alone can repeat the first page. Unsupported cursor formats stop safely instead
of guessing, and batch errors include a sanitized phase/reason in the dashboard.

The UI's Rare and Back-catalogue buttons stage editable presets only: they do not
save settings, start requests, or enable automation. Rare defaults to 1970–2015,
10–5000 IMDb votes, runtime at least 30 minutes and three pages per service.
The start offset defaults to zero because a narrow filtered catalogue may be
small. Vote count is only an obscurity hint, **not proof of tracker absence**.
Missing vote/runtime data cannot satisfy an active bound.

Explicitly unreleased titles, unknown/future release years and ambiguous provider
IDs are skipped. Filters apply before queue selection limits so older popular
queue entries cannot starve the rare-title budget. Checks are balanced across
services. Queue rows show available year/votes/runtime evidence.

In movie `absent_all` mode, selected trackers are checked in order and the FIRST
verified hit stops all remaining tracker/provider requests. Unknown results never
count as absence. The final profile-dependent check also stops after a hit.
Other eligibility modes retain their own explicit slot/missing-any semantics.
Two consecutive provider/metadata errors defer that provider for the current run.
A definitive per-title **unavailable** result is not a provider outage: the
runner continues to later candidates within the same check/API budgets. Empty
Netflix metadata is classified only for the exact requested native item; null
transport responses, errors and mismatched identities remain unknown and cannot
authorize a download.

Select `tv` in `media_types`. A catalogue series expands newest season first.
`max_episodes_per_title` bounds **new queue entries** per series scan; existing
unstarted entries can be refreshed without starving later episodes.
`max_series_expansions_per_run` and `max_checks_per_run` bound work separately.
Series refreshes are delayed by `series_refresh_minutes`.

- Movie key: exact IMDb ID.
- Episode key: exact IMDb ID + integer season/episode.
- Series discovery parent: separate `series:` key; it cannot reserve a download.
- Specials require explicit opt-in. Ambiguous/fractional/duplicate numbering is
  not guessed, even when a small page limit would otherwise hide the duplicate.
- Full manifest metadata is fetched for the requested episode only, not every
  episode in its season. Only sanitized selection plans are retained in memory.
- Download quotas count each episode, not each series.

Deduplication spans services. A completed, started, failed, or uncertain payload
job is never automatically replayed when the catalogue is rediscovered.

## Ledger, retries, and recovery

An immutable attempt ledger enforces global and per-service UTC start limits.
A reservation consumes a start even if the CLI fails or times out. Series
expansion and dry-runs consume no download starts. Reaching all relevant daily
limits prevents an execution run from making another discovery/API scan.

Unknown checks use bounded exponential backoff, preserved across rediscovery.
Rule/filter changes invalidate unstarted planning evidence, not terminal jobs
or the attempt ledger. Settings and explicit queue changes share the standalone
worker's file lock. A scheduler waiting for a settings change rechecks that it
is still enabled before launching.

The queue's **Recheck** action only queues fresh verification; it does not
contact APIs or start a download. Failed/uncertain payload retries require the
operator to establish that the old process is stopped and no completed payload
exists, then type `VERIFIED NO PAYLOAD`. This does not refund daily starts.
Currently started and completed jobs cannot be replayed through this action.
No automatic partial-media deletion is provided.

A successful CLI exit is recorded as such, **not as independently verified
payload completeness**. Do not infer that the resulting media is upload-ready.

## Dedicated configuration

Server-only fields are not browser-editable. A typical Docker setup adds:

```json
{
  "verify_cardinal": true,
  "ua_root": "/home/artemis/apps/upload-assistant",
  "cardinal_exchange_host": "/home/artemis/docker_compose/cdl/temp/ua-catalogue-metadata",
  "cardinal_exchange_container": "/tmp/ua-catalogue-metadata",
  "eligibility": "absent_all",
  "media_types": ["movie"],
  "include_specials": false,
  "max_episodes_per_title": 30,
  "max_series_expansions_per_run": 2,
  "series_refresh_minutes": 60,
  "metadata_timeout_seconds": 180,
  "slot_timeout_seconds": 180
}
```

Validate the real Docker bind mapping and UID/private permissions before using
these example paths. The trusted UA config is the runtime
`~/.local/state/upload-assistant/data/config.py`, not a checkout default.
Provider regions in this dashboard do not rewrite Cardinal's proxy profiles;
keep the corresponding existing profiles consistent.

The legacy native-binary movie-absence path remains for compatibility. Advanced
metadata/TV/slot workflows require the validated dedicated Docker adapter.

## UI and privacy

Queue reads use read-only SQLite connections in worker threads, bounded caches,
DB/WAL-aware revisions, filtering, and pagination. Lightweight status excludes
queue rows. Polling adapts to active/idle work and pauses for hidden tabs;
search is debounced and stale responses cannot overwrite newer selections.

Only loopback `127.0.0.1:8777` is served by the backend, reached through private
Tailscale TCP Serve. Never install a public proxy or enable Funnel. Existing
public `/catalogue` routes must continue to return 404. See
[catalogue-dashboard.md](catalogue-dashboard.md) for private access and service
operations; `catalogue-nginx.conf` is deny-only.

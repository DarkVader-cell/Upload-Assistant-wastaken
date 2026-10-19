# Tracker network recovery and actionable slot diagnostics

## Network policy

The tracker-status duplicate search and bandwidth recheck now retry **explicitly
read-only** operations up to three times. This includes read-only provider search
callbacks that use POST, not just HTTP GET. Connection/read/pool timeouts,
connection resets/protocol failures and temporary HTTP 408/429/5xx/Cloudflare
errors receive bounded jittered backoff. Authentication/validation errors and
certificate-verification failures do not retry. A Retry-After longer than the
bounded wait is **not shortened**: the operation fails/defer rather than retrying
early. Cancellation propagates.

UNIT3D searches have a 45-second read budget and 15-second connection/pool
budgets, rather than a single 10-second timeout. Optional detail/MediaInfo reads
get two attempts; an unavailable detail stays unknown and is labelled, not
fabricated. API IDs get a canonical details link when the search API omits it.

Upload submission is **not** treated as a read:

- UNIT3D retries only an original-endpoint connect/pool failure before submission;
  not an error on a redirected request. TLS certificate failure is never bypassed.
- Read/write timeout, connection reset after sending, server 5xx or an unreadable
  response may mean the tracker already accepted the upload. Mark outcome unknown,
  stop automatic resubmission and ask the operator to check the site first.
- 401/403/422/429 are not accidentally re-posted by falling through a retry loop.
- Once the API acknowledges success, result parsing and torrent downloads cannot
  repeat the upload POST. The site-success state remains distinct from pending
  client injection.
- Upload response timeout is 180 seconds, connect/pool 15, write 120.

These changes improve client handling; they do not promise to eliminate tracker,
DNS, proxy, WAF or network outages. Certificate checks are not disabled. Existing
non-UNIT3D upload adapters retain their adapter-specific submission handling.

## Tracker torrent download integrity

The common downloader retries the safe GET into a fresh, private temporary file.
It validates bencode/torrent structure (including v1 parsing) and atomically
replaces the generated local torrent **only after** a complete valid download.
Interrupted streams, HTTP errors, login HTML and invalid metadata do not truncate
the existing file. Temporary downloads are removed on failure/cancellation.

If a required official tracker torrent cannot be obtained, client injection is
deferred rather than injecting an unconfirmed fallback. The site upload may still
have succeeded: download its official torrent manually; **do not resubmit** the
upload to repair a download problem. Diagnostics show phase, error class/HTTP
status and retry count without dumping authenticated URLs or response bodies.

## What the slot panel now means

1. **Existing releases affecting this decision**: exact torrent ID, release name,
   link, parsed resolution/format/codec/range, and a per-release reason. Names
   remain visible even with embedded links disabled. Shared by-slot decisions
   retain the individual comparison reason, not just the first generic summary.
2. **Related releases — context only, not trump targets**: e.g. HD source behind
   an SD restriction, 2160p source precluding Aither 1440p, WEB-DL needing a
   WEBRip comparison, or original/derived HDR coexistence. These references never
   enter `conflicts` or become report targets merely because they are displayed.
3. **Required checks for this upload**: BLU lists its actual unmet checks, including
   detected screenshot count and missing audio-language/report facts. The long
   legacy paragraph and unconditional whole-site reminders are not repeated.
4. When no particular existing release caused the check, the panel says so. An
   eligibility/provenance check is not presented as a duplicate, and does not prove
   that a slot is vacant. A failed search explicitly means **occupancy unknown**;
   stale cached title lists do not establish vacancy. Known MUST blocks remain
   blocks; required reviews are default-No attended and skipped unattended.

BLU no longer gives a Blu-ray-source encode a WEBRip-versus-WEB-DL restriction
merely because the title has a WEB release. TV replacement guidance is not made
an unconditional unmet requirement for an otherwise vacant TV slot.

Display references contain only names/IDs/details links/traits, not copied
credential-bearing download URLs. Conflicts/protected IDs and successful-upload,
explicit-target report safeguards are preserved. Context cannot authorize a trump.

The panel bounds long lists at 25 references and says when more are omitted.
Actual quality, source lineage, grade checks and staff approval still require
real evidence; a descriptive panel does not manufacture any of them.

# Upload Library

Open **Upload Library** in UA's module navigation (`/upload-library`).
It lists release paths across recorded attempts, combining successful tracker
results so a later failure does not erase an earlier success.

- Search by release name/source path.
- Filter by one or more configured trackers: no recorded success, uploaded,
  failed, or never selected. Multiple trackers use **any-match** semantics.
- Filter by category, resolution, or recorded errors.
- Paginated selection, select page, select all filtered, and clear selection.
- Retry selected releases to selected trackers. Targets already recorded
  successful are excluded; missing/out-of-root sources are reported as skipped.
- Import retained `tmp/*/meta.json` snapshots using the explicit import button.
  Import is bounded to 5000 metadata files of at most 8 MiB each and is idempotent
  for unchanged snapshots. It does not contact trackers or scan media disks.

Retries submit to the existing UA WebUI execution/session queue, with ordinary
path validation, concurrency limits, duplicate checks and tracker rules intact.
They run unattended, so reviews requiring manual approval remain stopped.
The page reports execution requests, **not** final upload success: inspect the
normal UA sessions for queue admission, detailed errors and final results.
The retry API validates at most 50 releases per request; the browser batches
larger selections. A full queue can reject requests; inspect sessions rather
than blindly retrying ambiguous/disconnected requests.

New completed processing attempts and unexpected failures are recorded in the
existing release-history SQLite database, governed by its configured retention
(default 5000 records). Missing/failed means **local evidence only**, never proof
that a release is absent from a tracker. Old uploads lacking retained history
or metadata cannot be reconstructed automatically. Error filters use recorded
failed tracker outcomes and failed attempt status; raw error logs/credentials
are not exposed by this module. Historical per-tracker error text is unavailable
when it was not recorded. Successful tracker outcomes are combined by exact
source-path string; moved paths are not guessed to be the same payload.

Authentication protects all routes, and mutations require CSRF plus same-origin
validation. Browser selections reference server-derived release IDs rather than
accepting arbitrary retry paths or arguments. History paths are revalidated
before creating a retry plan and again by the actual execution endpoint.

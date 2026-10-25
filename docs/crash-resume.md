# Crash recovery and reconnects

A browser disconnect reattaches to the same session; it does not submit another
upload. SSE responses disable proxy buffering and transformation. Informational
colon-terminated log lines are not input prompts and must not start an unattended
prompt timeout.

For a restarted CLI process, new runs retain these independent checkpoints:

- Completed MOVIE/TV preparation, bound to source paths/inodes/sizes/mtimes,
  companion files, input options/default settings and preparation-code version. Required MediaInfo and
  payload files must still exist. Confirmed metadata corrections are retained;
  upload overrides, tracker permission/dupe results and one-shot confirmations
  are not. Current default/explicit tracker selections are resolved afresh.
  Normal current-run tracker checks still apply to new uploads. Changed options,
  missing artifacts, expiry, `--delete-meta`, or `--delete-tmp` force preparation.
  A changed source/companion fingerprint stops reuse of that work directory:
  choose a fresh work directory, or clear isolated UA temporary artifacts with
  `--delete-tmp`. Never use that flag if the input overlaps UA's temporary tree;
  choose a separate `UA_DATA_DIR` instead. The checkpoints themselves do not
  remove original payloads.
  Disc, music, game and book preparation keep their existing paths rather than
  blindly restoring video metadata. `stage_checkpoints_enabled: false` disables
  preparation reuse; `--no-metadata-cache` also disables it. Credential-bearing
  reference values are redacted; a snapshot that lost such values is not reused
  as if its image/description metadata were complete.
- Each acknowledged image-host response, keyed by exact local image fingerprint
  and host. A restart reuses completed images rather than starting the entire
  screenshot batch again. Changed images invalidate their entries. Image POSTs
  that did not return/persist a response may need repeating; they are not tracker
  submissions. Private image-progress files contain only public response URLs,
  never upload/delete API tokens. Reused responses do not count as new network
  uploads.
- Tracker submission intent **before** the upload method is called, and a durable
  acknowledgement before client injection. SQLite atomically prevents two
  processes claiming the same submission. A previously acknowledged submission
  is not POSTed again; the exact retained torrent is digest-checked and restored
  for idempotent client registration, before new-upload eligibility/reporting
  gates. This does not grant permission for a new upload or repeat a trump report.
  These copies are private (0600 under a
  0700 directory). Missing/corrupt retained torrents require on-site retrieval,
  never guessing from names or sizes. An unchanged work-directory torrent may
  substitute for a lost cache copy only when its recorded digest matches exactly.

Generated WebUI selections resume only the same content/options/tracker scope.
Changing targets (including configured defaults) does not silently skip files
because they were previously sent elsewhere. Partial upload failures or pending
client-review states are not marked as fully processed queue items.

An interrupted POST without an acknowledgement is genuinely ambiguous. Check
whether the release reached the tracker. Only after verifying that it did not,
use the attempt-specific instruction printed by UA:

```text
--confirm-not-uploaded AITHER:REVIEW_TOKEN_FROM_THE_MESSAGE
```

This is a one-shot permission tied to that interrupted attempt. A new POST rotates
the token, so an old argument retained in retry history cannot authorize another
retry. It cannot override an actively running submission or bypass duplicate,
slot, evidence or protected-torrent rules. `--delete-meta` and `--delete-tmp` do
not erase submission acknowledgements (stored outside the preparation folder).

These checkpoints are not retroactive proof of uploads made by older versions.
Existing remote `needs_review` jobs still require explicit recovery and keep
payloads. No automatic replay of ambiguous tracker uploads is introduced.

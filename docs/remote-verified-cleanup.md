# Verified VPS cleanup after return

Set `auto_cleanup_verified` to the JSON boolean `true` in the dedicated host's
private remote-backend/shuttle configuration to enable automatic cleanup. It
is **off by default**. The existing return timer checks this option on each run.
The upload job becomes `cleaned` only after verified cleanup succeeds; otherwise
it remains `returned` with a blocked cleanup reason and retries after five
minutes. Dedicated originals are never deleted.

Cleanup is stage-scoped, not a sweep of the VPS. Every related torrent must have
a verified returned/cleaned record, and the stage must have no active or
unresolved tracker handoffs. Dedi registrations are checked by exact infohash,
complete state, save path and torrent pieces. Identical piece layouts over the
same unchanged inodes can share a proof within that one cleanup operation;
different layouts require their own proof. File fingerprints are checked again
before any remote deletion. No qB recheck is requested.

The VPS worker preflights the complete selected batch before unlinking anything:

- no active UA upload process;
- complete remote qB reference inventory, refreshed after hash checks;
- recorded inode identities for every returned tracker link;
- stage manifest and checksum proof for original staged payloads;
- all hardlinks accounted for by that exact cleanup plan;
- no unknown files, symlinks or unusual objects inside the staged payload tree.

Any refusal retains the data. Concurrent changes during unlinking stop the
operation; retries are idempotent for already-removed recorded links. Audit
records remain. Failed/unrelated stages are not selected.

For explicit operator-approved cleanup of specific already-returned batches:

```bash
python -m src.remote_upload --config /private/backend.json cleanup \
  --stage VERIFIED_STAGE_ID --stage ANOTHER_VERIFIED_STAGE_ID
```

This command performs the same checks and does not copy/recheck anything through
qB. It does read payload bytes for the independent cleanup proofs. Never select
stages by name/size or edit a failed handoff to make it appear returned.

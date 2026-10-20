# HBD raw-file shuttle (SSH TUI)

This is a **raw-file staging** workflow. No original torrent is required to copy
selected Dedi files to the small shared SSD VPS. UA creates new tracker torrents
on the VPS afterward. Return transfers those registrations to Dedi without
copying/deleting Dedi's original payloads.

## Workflow

Run `~/.local/bin/ua-hbd-shuttle` after SSHing to Dedi. The deployment must first
install its isolated Paramiko environment, verified peer host key, private
configuration and matching worker on the VPS.

1. **Stage raw file/directory via SFTP**: arrow-key filesystem selection under
   configured media roots. Copies directly Dedi→VPS over encrypted, pipelined
   SFTP; verifies SHA-256 at both ends. Source files stay on Dedi. Changing files,
   symlinks, unusual objects, unsafe paths and insufficient free space fail closed.
2. **Run UA on a verified staged item**: opens the VPS UA interactive CLI in an
   SSH terminal. Select trackers normally. The VPS configuration uses only its
   local qB, native `/ → /` paths and hardlinks under `ua-hbd-staging/Uploads`.
   No permanent extra WebUI/worker is needed on the small box.
3. **Return selected completed VPS torrents**: display category/tags/save path,
   require typed `RETURN`, request a source reannounce, map payloads by staged
   inode provenance (never name/size guesses), verify the exported exact infohash
   and every v1 piece against Dedi originals, then create non-overwriting Dedi
   hardlinks. Seed-mode import follows **only** that independent full-piece proof;
   it avoids adding huge recheck jobs to the overloaded Dedi client. Preserve
   category, tags, limits, priorities, automatic management where its category
   path is safe, display name and intended stopped/forced/running state. Verify
   the final registration before removing only the selected VPS registration.
4. **Clean verified SSD copies**: separate explicit confirmation. Re-verifies
   exact Dedi pieces. Never calls qB `deleteFiles=true`. Removes only recorded
   returned VPS links without live torrent references; original staging copies
   additionally need link count one and their original checksum. Active UA
   sessions defer cleanup. Unknown files/audit records are not recursively deleted.
   A successful cleanup marks the exact returned records and stages as `cleaned`,
   retaining their audit records without making later cleanup retry an already-
   removed VPS registration.

The free-space reserve is 8 GiB. This VPS was inspected with **27.8 GiB free**, not
100 GiB free; UA/Python dependencies reduce that slightly. Do not delete existing
VPS downloads to make room without explicitly inspecting/authorizing them.

## Guarantees and deliberate refusals

- No Dedi original deletion, overwrites, unfiltered Dedi torrent inventory calls,
  qB/Deluge restarts, or modifications to unrelated existing registrations.
- Reannounce means a successful API **request**, not proof of tracker receipt.
  A stopped selected source is temporarily started for the requested announce,
  then restored/stopped as appropriate. No tracker minimum-interval bypass.
- Hashes already present on Dedi, ambiguous origins, changed originals,
  unsupported renames, v2/padding/symlink layouts, category-path conflicts,
  different tracker URL/tier state or verification failures are refused rather
  than silently changing settings or deleting source data.
- A qB historical `added_on` date, uploaded-byte total and accumulated local
  seeding-history counter cannot be transplanted through the Web API. Tracker
  account/hash history is not rewritten. Resume files are never patched.
- No source torrent is needed until the **return** step. Missing historical
  staging records do not authorize deletion by a matching filename/size.
- Interrupted/failed transfers and `needs_review` records retain data. If a
  return fails after temporarily stopping a previously running VPS torrent, the
  shuttle attempts to restore that source registration to running; the record
  remains `needs_review` if any step failed. Inspect the private ledger and both
  exact registrations before retrying; automatic recovery/discard of ambiguous
  partial states is deliberately not enabled.
- UI filesystem lists are bounded at 1000 entries per directory and the return
  picker currently shows the first 200 completed VPS torrents. No global Dedi
  scan is used to populate either picker.

## Private configuration

`~/.config/ua-hbd-shuttle/config.json` references each host's private UA config
and local qB client; it does not duplicate passwords in the Dedi TUI config.
The interactive SSH password is prompted, not saved. SSH host-key checking is
strict. No authorized keys or password resets are installed.

The private ledger is `~/.local/state/ua-hbd-shuttle/ledger.json` on Dedi (0700
directory, atomic 0600 writes), with a matching verified payload manifest on the
VPS. Do not manually remove/edit it to bypass an origin/verification refusal.
Cookie-based trackers may require their own VPS login; API configuration copying
does not claim to migrate IP-bound browser sessions.

## Validation/deployment status

Tests use synthetic files and fake qB/SSH peers; they must not submit real
tracker torrents/reports. Check the operator's final deployment report before
assuming the launcher is installed. Source code alone is not an installed,
verified service.

# Remote upload jobs (CLI module)

Run on the dedicated/payload-owning host. This module reuses the existing
`tools/hbd-shuttle.py` verification engine, not a second file-migration engine.
The selected remote host creates the torrent using its own CPU/NVMe through UA.

## Configuration

Use a private shuttle config as described in [hbd-shuttle.md](hbd-shuttle.md).
The backend is configurable: `remote.host`, `remote.port`, `remote.user`,
`remote_script`, `remote_ua_command`, `known_hosts`, `stage_root`, `source_roots`,
`target_roots`, `return_root`, `state_dir`, `reserve_bytes`, and local qB settings.
Use distinct state directories/config files for distinct remote hosts. No
provider name or address is hardcoded into the module.

For unattended return, an **existing authorized SSH key** can be selected with
`ssh_key` (absolute filename). The module never installs keys or stores SSH
passwords. Without a key the existing interactive password prompt is used.
Host-key verification is mandatory. Both hosts need the matching shuttle worker
and their own private UA/qB configuration installed before use.

## Commands

```bash
# Copy and checksum-verify a source, retaining the dedicated original.
python -m src.remote_upload --config ~/.config/ua-hbd-shuttle/config.json \
  stage /approved/media/Film.mkv --return-after 86400
# Prints a job ID. Start UA interactively on the selected remote NVMe copy.
python -m src.remote_upload --config ~/.config/ua-hbd-shuttle/config.json \
  upload JOB_ID --trackers PTP HDB
# Display persistent jobs without connecting.
python -m src.remote_upload --config ~/.config/ua-hbd-shuttle/config.json status
# Return eligible exact registrations (may be called by a user timer).
python -m src.remote_upload --config ~/.config/ua-hbd-shuttle/config.json tick
```

The interval is measured conservatively from completion of the remote UA
session, not the original staging time. Only newly created remote qB
registrations whose every file has verified provenance in the selected stage
are adopted. Older/unrelated torrents are not scheduled.

`tick` requests a remote reannounce and uses the existing return engine to
verify every v1 piece against the dedicated originals, create non-overwriting
hardlinks and import the exact torrent in seed mode. It does not enqueue a qB
recheck or copy payload bytes back. Reannounce request success is **not** proof
of tracker receipt. There is no tracker minimum-interval bypass.

The controller ledger lock prevents simultaneous workers. Failed or interrupted
uploads/returns are never automatically replayed; inspect `needs_review` and
`uploading`/`returning` states manually. Retain the ledger for recovery. SSD cleanup
remains the explicit verified shuttle cleanup operation; the scheduler never
deletes payloads. Existing registrations on the destination are not overwritten.

## WebUI

Set `UA_REMOTE_UPLOAD_BACKENDS` on the **dedicated host's** UA service to an
absolute filename containing an operator-controlled JSON mapping, for example:

```json
{"nvme-vps": "/home/artemis/.config/ua-hbd-shuttle/config.json"}
```

Keep the registry/config private (directory 0700, files 0600). Restart UA after
setting the environment. Open **Remote uploads** from UA or `/remote-upload`.
Choose a backend, enter an approved dedicated source path, trackers and interval.
The page submits staging and unattended UA to a detached worker so it survives a
WebUI process restart. View jobs and operation states with **Refresh status**;
**Process due returns now** runs the same verified scheduler as the timer. One
pending WebUI operation per backend prevents duplicate/flooded launches.
Authentication, same-origin and CSRF checks protect submissions. No backend
credentials or worker output are returned to browsers.

A crashed worker may leave `queued`/`running` records. Inspect its process and the
shuttle ledger before manually marking that operation `needs_review`; do not
blindly resubmit. Upload POSTs and ambiguous returns are never auto-replayed.
WebUI input is restricted to explicit tracker IDs and backend-approved roots;
arbitrary SSH arguments and configuration paths cannot be submitted.

## Automatic return timer

On the dedicated host as the service owner:

```bash
python scripts/install-remote-upload-timer.py \
  --config ~/.config/ua-hbd-shuttle/config.json \
  --python "$PWD/.venv/bin/python" --name nvme-vps --enable
systemctl --user status ua-remote-return-nvme-vps.timer
```

This installs a persistent minute-resolution timer. It runs the exact same
locked, provenance-verified `tick`, never an upload or cleanup command. Jobs
retain their due times across service/host restarts. The administrator must
ensure the user's systemd manager survives logout (lingering). An existing SSH
key is required; the installer does not install authorized keys or passwords.
A timer running during an interactive shuttle operation safely fails its lock
and retries at the next scheduled tick. Duplicate handoffs are never started.

## Limits

Remote installation, automatic replay of ambiguous transfers, per-tracker
announce acknowledgement, automatic SSD deletion, and transplanting qB history
counters are deliberately not implemented. Dummy tests use fake peers and qB
responses; they never upload real torrents. Source-path entry is supported in
the WebUI; a remote browser/drag-and-drop picker is not implemented.

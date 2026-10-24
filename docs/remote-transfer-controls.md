# Remote transfer performance and interactive jobs

## Protocol and throughput

Each backend's private shuttle JSON supports `transfer_protocol`:

- `rsync`: native OpenSSH with IPv4, strict pinned host keys and key-only auth;
  one whole-file stream, no compression or delta-signature scan, in-place writes
  only inside a newly prepared stage. Requires `/usr/bin/rsync` on both hosts.
- `sftp`: existing pipelined Paramiko fallback. This remains the default unless
  the operator explicitly selects native transfer for the backend.

`ssh_ciphers` optionally selects an OpenSSH cipher list. The native default is
`aes128-gcm@openssh.com,chacha20-poly1305@openssh.com,aes256-gcm@openssh.com`.
No host-key, encryption or integrity checks are disabled for speed. Native SSH
avoids Python SFTP packet/encryption overhead, but throughput still depends on
source disk, CPU allocation and the VPS/network cap. No maximum speed is promised.

After native copying, UA checks original fingerprints. `verify_stage_sha256`
(default true) optionally adds full SHA-256 reads on both hosts. Set it to false
to skip those extra post-copy reads: authenticated SSH completion, file sizes
and unchanged original fingerprints remain checked. Transfer progress/ETA covers
copying, not an optional hash phase, tracker interaction or return. The independent
exact torrent-piece proof before seed-mode return is NEVER disabled. Its existing
read also supplies checksum proof for later explicit VPS cleanup; cleanup is
refused without staging or exact-return proof.

## Interactive Upload-form workflow

Selecting a remote destination in the normal Upload form now submits to the
**existing WebUI execution session**, not a detached unattended upload worker.
After staging and verification, remote UA inherits that session's input/output
through key-authenticated SSH without a PTY. Normal prompts appear in the same
terminal and answers use the existing Send Input controls. Unattended mode is
not added automatically. A user-specified unattended flag still means unattended.
The remote invocation forwards UA's color/progress/prompt environment, never the
dedicated host's browse-root restrictions or arbitrary environment credentials.

This bridges interactive terminal prompts, not remote temporary artifacts:
the dedicated host's local screenshot/MediaInfo preview endpoints do not yet
mirror all VPS-side temporary files. Keep the terminal open for remote reviews.
Old jobs submitted through the detached remote API remain unattended; running
jobs cannot be retroactively converted without interruption.

## Launch environment and recovery without another copy

SSH does not inherit a systemd service's environment. Configure
`remote_ua_command` with the same data directory as the existing VPS UA service,
for example `["/usr/bin/env", "UA_DATA_DIR=/path/to/active/ua", "/path/to/python",
"/path/to/upload.py"]`. Do not move/delete a live client's configuration to fix
an omitted SSH environment variable.

A ready stage whose UA launch failed can offer **Use staged copy — no transfer**
in the Remote workspace. It prepares the normal upload form with the existing
stage ID and prior tracker targets. Starting it creates an explicit new attempt
without recopying or rehashing the payload; source fingerprints and remote
inode provenance must still match. The prior needs_review record is retained,
and normal UA duplicate/policy checks apply. Review any prior tracker outcomes
before retrying; this is never an automatic replay.

## Pause / resume / cancel / partial removal

New stages record their local writer PID, process start identity and process
group. The Remote workspace can pause/resume that group while it is copying.
Cancellation wakes a paused writer and interrupts the recorded job. It does
**not** delete VPS data or dedicated originals. PID-reused, legacy, completed or
uploading stages are not signalled through the transfer controls.

A paused connection can still expire due to remote/network timeouts; resume
is not a promise of recovery after a broken SSH connection. An interrupted job
is retained for inspection, never automatically replayed as a new upload.

Partial removal is a separate confirmed action after the writer has exited.
The controller takes its exclusive lock, and the remote worker refuses removal
if uploads are active, qB references are incomplete, files are referenced or
hardlinked, symlinks/unusual files appear, or unknown payload files exist. It
removes only regular files listed in that exact private stage manifest. Audit
records and dedicated originals remain. Ready/uploaded/returned stages use the
existing verified-return cleanup workflow instead.

Transfer controls are not available for legacy jobs lacking writer identity.
The normal session Kill control still stops its local process tree. Cancelling
an already-started remote upload may leave an ambiguous remote operation, so
inspect it before retrying; no deletion or automatic retry is authorized by it.

Return scheduling remains persistent. Its due time starts after remote UA
finishes; a busy controller lock can defer return beyond the nominal interval.
Every due tracker torrent goes through the same exact-torrent proof and
`skip_checking=true` seed-mode import. UA never requests a qB full recheck. If qB
nevertheless reports full checking of the new registration, UA stops/removes
that exact destination registration with `deleteFiles=false`, retains the VPS
source and marks the handoff for review. Fast resume-data processing is not a
full payload recheck and may briefly occur during import.

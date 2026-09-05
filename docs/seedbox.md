# Seedbox / Linux Install

This guide covers installing Upload Assistant on a Linux box or seedbox where you do not have root access.

## What this installer does

The bundled installer script:

1. Installs `pyenv` if needed.
2. Installs Python `3.14.0` by default.
3. Uses the current checkout if you pass `--ua-dir`, or clones/updates Upload Assistant in `~/tools/ua` by default.
4. Creates `.venv`.
5. Installs the base dependencies from `requirements.txt`.
6. Creates `run-ua.sh` for easier execution.

## Quick start

From a Linux shell:

```bash
git clone https://github.com/wastaken7/Upload-Assistant.git
cd Upload-Assistant
chmod +x scripts/install-seedbox.sh
./scripts/install-seedbox.sh --ua-dir "$PWD"
```

If you just want the installer to create or update a separate checkout in `~/tools/ua`, omit `--ua-dir "$PWD"`.

## Options

```text
--ua-dir PATH           Installation directory (default: ~/tools/ua)
--python VERSION        Python version for pyenv (default: 3.14.0)
--skip-pyenv-install    Fail instead of installing pyenv automatically
--force-update          Recreate .venv and reinstall packages
-h, --help              Show this help
```

## Requirements

These commands should already exist on the seedbox:

```bash
bash --version
git --version
```

To build Python with `pyenv`, many providers also need common build tooling already installed, such as:

```bash
gcc --version
make --version
```

If your provider compiled the host without the required development libraries, Python modules such as `_sqlite3` may still be unavailable. In that case, the fix is on the provider side, not in Upload Assistant.

## Running Upload Assistant

After installation:

```bash
cd /path/to/your/ua/checkout
./run-ua.sh "/path/to/content" --trackers yourtracker
```

If you prefer the raw environment:

```bash
cd /path/to/your/ua/checkout
source .venv/bin/activate
python upload.py "/path/to/content" --trackers yourtracker
```

## Whatbox deployment used by this project

The Whatbox HDD instance uses the `grape.whatbox.ca` SSH host, rootless Podman,
and the deployment directory `~/Upload-Assistant-wastaken`. The WebUI container
is `upload-assistant-wastaken`, is defined by `docker-compose.local.yml`, and
pulls `ghcr.io/darkvader-cell/upload-assistant-wastaken:latest` directly.
This is a standalone container: it does not require Gluetun, Radarr, or
Sonarr. Radarr/Sonarr metadata integrations remain optional application
features.

Connect and inspect it with:

```bash
ssh artemisprime@grape.whatbox.ca
cd ~/Upload-Assistant-wastaken
podman ps -a
```

```bash
podman compose -f docker-compose.local.yml up -d upload-assistant-wastaken
podman logs --tail 100 upload-assistant-wastaken
```

The WebUI is exposed on port `12345`, for example
`http://grape.whatbox.ca:12345` when the Whatbox firewall allows that port.

Restart without rebuilding:

```bash
podman restart upload-assistant-wastaken
```

Update to the latest published fork image without building on Whatbox:

```bash
podman compose -f docker-compose.local.yml pull
podman compose -f docker-compose.local.yml down
podman compose -f docker-compose.local.yml up -d --no-build upload-assistant-wastaken
curl -fsS http://127.0.0.1:12345/api/health
```

Apply the same update to the Clementine client from its own checkout; its
WebUI health endpoint is on port `12346`. With the installed
`podman-compose`, use `up -d --no-build` after the pull. Do not add
`--force-recreate`: that version can remove the old container before raising
an internal error. The normal `up -d --no-build` command recreates a missing
or changed UA service safely.

The current published image creates a checkout-default configuration during
startup. Keep `UA_DATA_DIR=/Upload-Assistant` and the existing
`docker-data/data:/Upload-Assistant/data` mount in the homelab and Whatbox
compose files until that image-level migration is corrected. This is a
compatibility setting, not a data migration; it preserves the existing
configuration and avoids the image rejecting the config it creates itself.

If Podman reports a stale pod with no infra container, remove only that named
pod and recreate the service; persistent `docker-data/` mounts are unaffected:

```bash
podman pod rm -f upload-assistant-wastaken
podman compose -f docker-compose.local.yml up -d --no-build upload-assistant-wastaken
```

Do not remove the persistent `docker-data/` directories when recreating the
container.

### Clementine SSD-to-Grape handoff

The worker migrates completed `Uploads` tracker hardlinks and, once every
related tracker handoff is verified and the source is no longer hardlinked,
also migrates the original `To_Upload` torrent and qBittorrent registration.
The retained `to_upload` tag does not block this verified original migration.
Completed BeyondHD originals with no UA `Uploads` representation are handled
as direct sources through the same exact-torrent verification path. If tracker
hardlinks are attached on Clementine, their batch completes first and the
original reuses the verified Grape payload as a destination hardlink.
Sources remain age-gated; ordinary UA originals also retain their upload-lifecycle
gate until they satisfy the verified source conditions. Historical non-BeyondHD
originals without matching handoff state still require the explicit non-Uploads
QUI recovery action; otherwise a cross-seed search may be needed to reconstruct
the missing original seed.

Completed tracker hardlinks are handed from Clementine's SSD to Grape only
after their local upload window. The credential remains on the homelab host;
the local retry timer invokes the worker every 15 minutes (with a small random
delay), while QUI remains available for an immediate selected release.
The worker takes an exclusive lock, so a manual QUI request, a retry, and the
periodic watcher cannot copy or delete the same torrent concurrently.
The Clementine-to-Grape SSH and rsync legs force IPv4 (`-4`); Whatbox advertises
an IPv6 address for the Grape hostname that is not reliable from Clementine.

For each eligible batch, the worker:

1. Reannounces all eligible source torrents and waits 120 seconds before any
   copy begins, including a delayed retry after an outage, giving trackers time
   to record final source-side statistics.
2. Copies the payload resumably to Grape, or makes a hardlink to an already
   transferred identical inode. This keeps duplicate tracker releases to one
   physical Grape copy.
3. Imports the exact torrent infohash into Grape qBittorrent. The importer
   waits up to 90 seconds for qBittorrent resume data and requires a complete,
   seed-ready registration.
4. Removes the Clementine tracker hardlink only after that verification. The
   original SSD source is then copied and registered as its own exact torrent
   once all matching tracker handoffs have verified on Grape. A later cleanup
   pass removes the original only after that source handoff is verified.
   A failed or interrupted transfer leaves the source intact, records an
   exponential retry deadline in handoff state, and is retried by the timer.

#### Direct BeyondHD originals

A completed BeyondHD original can be handed off even when it was not created
by a UA `Uploads` hardlink. The worker copies the exact original torrent,
imports it into Grape qBittorrent, verifies it is complete and seed-ready, and
only then deletes the Clementine source. If the same SSD payload has attached
UA tracker hardlinks, those handoffs finish first; the original then uses a
Grape hardlink to their verified canonical inode. A source with remaining SSD
hardlinks, incomplete data, or an unsupported directory tree is skipped and
left intact for a later retry.

The handoff state is stored on Clementine in
`docker-data/data/handoff-state.json`; it records transfer stages and allows a
later watcher pass to resume safely. The matching `.torrent` metadata on
Grape is retained under `.ua-handoff/` for verification and recovery.

Original-source cleanup is deliberately conservative. It requires the
original torrent's own verified Grape registration; completed related tracker
handoffs alone never authorize deletion. A regular-file source
must have exactly one remaining SSD hardlink; a directory source is eligible
only when every regular payload file has one link and the tree contains no
symlinks or unusual filesystem objects. The worker also requires matching,
fully handed-off state—preferring the recorded inode identity and otherwise a
name plus total-payload-size match. These checks prevent it from deleting an
unrelated file after inode reuse or a partial cross-seed transfer.

Older non-BeyondHD sources with no matching `handoff-state.json` entry are
intentionally left on Clementine. Recover them with the QUI **Force selected non-Uploads
Clementine release to Grape HDD** action: it transfers the selected original
torrent, verifies it is seed-ready on Grape, and only then removes its SSD
source. Do not delete such historical sources merely because a similarly named
file exists on Grape.

If a historical entry is absent from Grape qBittorrent, do not re-add it by
name alone. Recover it only when its stored payload and torrent metadata match
the infohash. The Grape recovery path uses an additional hardlink under the
torrent's internal filename when necessary; it refuses missing, mismatched, or
multi-file payloads for manual review rather than risking a bad seed.

#### Forcing a completed release from QUI

Normal reconciliation intentionally leaves torrents tagged `to_upload` on
Clementine. When that tag remains after all intended tracker uploads are
finished, select the original or any matching tracker hardlink in QUI and run
the external-program action **Force selected Clementine release to Grape
HDD**. It resolves every completed `Uploads` hardlink for the same payload,
bypasses the tag gate, and handles the original source after those verified
handoffs complete.

Both single-file and directory releases are supported. Directory matching uses
the complete set of hardlinked payload files rather than the directory inode,
so matching tracker trees are included without treating unrelated directories
as duplicates.

The action is safe to invoke while a normal batch is active: it is accepted by
the local bridge and retries the remote worker's explicit busy result every 30
seconds. It does not copy, register, or delete anything until the existing
worker finishes; the normal state lock and infohash verification still govern
the transfer. Repeated clicks for the same selection are coalesced into one
pending request.

### Whatbox qBittorrent and Deluge reuse

The Whatbox deployment uses the host's qBittorrent Web API on port `17416` for
new injections. Upload Assistant runs with host networking so `127.0.0.1`
refers to the Whatbox host. Content is hardlinked into `Uploads/<TRACKER>`;
the original files remain under `files`.

Deluge remains enabled as the searching/reuse client. This allows an existing
Deluge torrent to be reused when its files match the current upload, without
bulk-importing all Deluge state into qBittorrent.

```python
"whatbox_qbittorrent": {
    "torrent_client": "qbit",
    "qbit_url": "http://127.0.0.1",
    "qbit_port": "17416",
    "qbit_user": "<qBittorrent username>",
    "qbit_pass": "<qBittorrent password>",
    "torrent_storage_dir": "/mnt/seeding/.config/qBittorrent/BT_backup",
    "qbit_cat": "Uploads",
    "linking": "hardlink",
    "linked_folder": ["/mnt/seeding/Uploads"],
    "local_path": ["/mnt/seeding"],
    "remote_path": ["/home/artemisprime"],
},
"whatbox_deluge": {
    "torrent_client": "deluge",
    "deluge_url": "<Whatbox Deluge RPC host>",
    "deluge_port": "58846",
    "deluge_user": "<Deluge username>",
    "deluge_pass": "<Deluge password>",
    "torrent_storage_dir": "/path/inside/container/to/deluge/state",
    "local_path": ["/mnt/seeding"],
    "remote_path": ["/mnt/seeding"],
},
```

Set `DEFAULT["default_torrent_client"]` and `injecting_client_list` to
`"whatbox_qbittorrent"`; keep `searching_client_list` set to
`["whatbox_deluge"]`. Correct local/remote path order is important: `local_path`
is how Upload Assistant sees the files, while `remote_path` is how Deluge
reports them. A successful reuse run logs `Found valid torrent in Deluge`;
otherwise it falls back to torrent creation and may run mkbrr.

## Updating

Run the installer again:

```bash
./scripts/install-seedbox.sh
```

Or update manually:

```bash
cd /path/to/your/ua/checkout
git pull --ff-only
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

## Notes about `local_path` / `remote_path`

`local_path` and `remote_path` are only path-mapping settings for torrent client integration.

They do not install UA remotely and they do not move Upload Assistant execution to another machine. If you want the heavy work to run on a remote file-hosting box, run UA on that machine directly or use the Web UI there and control it remotely.

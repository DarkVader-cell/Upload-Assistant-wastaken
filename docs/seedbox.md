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

The Whatbox instance uses the `cactus.whatbox.ca` SSH host, rootless Podman,
and the checkout at `~/Upload-Assistant-wastaken`. The WebUI container is
`upload-assistant-wastaken` and is defined by `docker-compose.local.yml`.
This is a standalone container: it does not require Gluetun, Radarr, or
Sonarr. Radarr/Sonarr metadata integrations remain optional application
features.

Connect and inspect it with:

```bash
ssh artemisprime@cactus.whatbox.ca
cd ~/Upload-Assistant-wastaken
podman ps -a
```

```bash
podman compose -f docker-compose.local.yml up -d upload-assistant-wastaken
podman logs --tail 100 upload-assistant-wastaken
```

The WebUI is exposed on port `12345`, for example
`http://cactus.whatbox.ca:12345` when the Whatbox firewall allows that port.

Restart without rebuilding:

```bash
podman restart upload-assistant-wastaken
```

After changing Upload Assistant source, rebuild and recreate it with:

```bash
podman compose -f docker-compose.local.yml up -d --build upload-assistant-wastaken
```

Do not remove the persistent `docker-data/` directories when recreating the
container.

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
    "remote_path": ["/mnt/mpathr/artemisprime"],
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

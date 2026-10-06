# Encrypted configuration export/import

Transfer selected settings from an authorized existing UA instance to a new machine without copying its runtime state. Bundles use AES-256-GCM authenticated encryption and a salted scrypt passphrase key. Use a unique passphrase of at least 12 characters. Keep the passphrase separate from the bundle.

## Export

Run in a checkout with UA dependencies installed:

```bash
uv run python scripts/config-bundle.py export \
  --config /path/to/state/data/config.py \
  --bundle setup.ua-bundle \
  --sections DEFAULT TRACKERS TORRENT_CLIENTS
```

The command securely prompts for and confirms the passphrase. It refuses to overwrite an existing bundle and creates it with mode `0600`.

`DEFAULT` exports selected metadata/Prowlarr credentials, API-key fields, image-host preferences, and the default tracker list. `TRACKERS`, `TORRENT_CLIENTS`, and `USENET` are explicitly selectable. Machine-specific `_path`/`_dir` fields, torrent storage directories, and client path mappings are excluded. Cookie files, sessions, caches, logs, and torrents are never packed. Literal inline credentials in selected sections **are** included, encrypted; export only sections you intend to share. There is no automatic remote credential discovery.

Copy the encrypted file through an authenticated connection such as SSH/SCP. Do not put the bundle or its passphrase into source control, tickets, or public URLs.

## Install on a bare Debian/Ubuntu host

```bash
bash scripts/install-instance.sh \
  --install-dependencies \
  --browse-root /srv/media \
  --install-dir "$HOME/upload-assistant" \
  --import-bundle /private/setup.ua-bundle
```

`--install-dependencies` explicitly authorizes package installation and Docker daemon setup through root/sudo. Other operating systems are not automatically provisioned: use the existing manual/native platform instructions. A supported Python 3.11+ must be available from the OS packages. Docker permission must be available to the invoking user (run as root or configure access explicitly); the script does not silently grant membership in Docker's root-equivalent group. Media directories must already exist.

The bundle import uses an isolated bootstrap virtualenv in Docker mode. Existing nonempty settings are preserved by default. Machine-local mappings and torrent storage directories must be configured and checked after import; remote Prowlarr/client URLs must be reachable from the container. Prowlarr indexers themselves are not cloned or enabled.

## Import into an existing instance

```bash
uv run python scripts/config-bundle.py import \
  --config /path/to/state/data/config.py \
  --bundle setup.ua-bundle
```

The command creates a private timestamped backup, locks the config, and replaces it atomically. `--overwrite` explicitly allows replacement of existing selected settings. The config is rewritten as a literal dictionary; comments are retained in the backup, not the new file. Nonliteral/dynamic configs are rejected, never executed. Restart UA to reload the imported settings.

For unattended use, supply `--passphrase-file /private/passphrase` (mode `0600` or stricter). The installer equivalent is `--bundle-passphrase-file`. Never supply the passphrase as a command-line value.

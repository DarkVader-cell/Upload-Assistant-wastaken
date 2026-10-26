# Portable instance installer

`scripts/install-instance.sh` bootstraps a new Linux Upload Assistant instance with a persistent Web UI, a mounted media root, and optionally Prowlarr credential fallback. It is designed for a new homelab host, VPS, or seedbox without copying an existing instance's configuration or secrets.

For saved profiles and a desktop shortcut, see [one-click configured installation](one-click-install.md). It reuses this installer with encrypted config/key bundles, Docker digest/revision pinning, live-instance refusal, and health verification.

Use `--install-dependencies` to provision Debian/Ubuntu packages with root/sudo, and `--import-bundle` to reuse selected encrypted settings from another instance. See [configuration bundles](config-bundles.md) for export, security, and limitations.

The default Docker mode needs Docker Engine, Docker Compose v2, Git, and Python 3.11 or newer for configuration bootstrapping. It runs the published fork image, so the application’s Python 3.14 environment is supplied by the container. Docker access must already be configured. Dependency installation is opt-in and currently supports Debian/Ubuntu only. Docker access must be explicitly configured; no root-equivalent group membership is granted silently.

## Docker installation

```bash
./scripts/install-instance.sh \
  --browse-root /srv/media \
  --install-dir "$HOME/upload-assistant" \
  --webui-port 5000
```

This creates:

- `data/config.py` — the user-owned UA configuration;
- `tmp/` — persistent queue, screenshots, and temporary state;
- `webui-auth/` — persistent Web UI session state;
- `.env` and `docker-compose.yml` — no tracker or Prowlarr secrets are stored here.

The media directory is mounted at `/data` and is the only Web UI browse root. The Web UI is available at `http://localhost:5000` unless a different `--webui-port` is specified.

Run the generated service manually when `--no-start` was used:

```bash
docker compose --env-file "$HOME/upload-assistant/.env" \
  -f "$HOME/upload-assistant/docker-compose.yml" up -d
```

## Prowlarr indexer credential fallback

Provide both a Prowlarr URL and its API key. Use a root-owned or user-only key file rather than putting the key in a shell command:

```bash
install -m 600 /dev/null "$HOME/.config/prowlarr-api-key"
# Paste the key into that file with a private editor.
./scripts/install-instance.sh \
  --browse-root /srv/media \
  --prowlarr-url http://prowlarr.local:9696 \
  --prowlarr-api-key-file "$HOME/.config/prowlarr-api-key"
```

Alternatively, use `--prompt-prowlarr-api-key`; the prompt does not echo the key.

UA reads enabled Prowlarr/Cardigann indexers at upload time and fills only **missing** supported tracker API keys and cookies in memory. Locally configured tracker credentials always win. The installer does not create, enable, or alter Prowlarr indexers: configure those in Prowlarr first. It makes a timestamped `config.py.backup-prowlarr-*` backup before changing an existing Prowlarr configuration. To change an already-created instance, add `--force-config` explicitly.

## Standalone seedbox mode

For a user-space Python/pyenv installation instead of Docker:

```bash
./scripts/install-instance.sh \
  --mode standalone \
  --browse-root /mnt/seeding \
  --install-dir "$HOME/upload-assistant"
```

This invokes `scripts/install-seedbox.sh`, uses the fork repository by default, and creates an instance-level `run-ua.sh` that sets `UA_DATA_DIR` to the instance directory. Start the Web UI with:

```bash
"$HOME/upload-assistant/run-ua.sh" /mnt/seeding --webui 0.0.0.0:5000
```

Configure torrent clients, mount/path mappings, trackers, and image-host credentials in the Web UI or `data/config.py` after installation. Use an explicitly selected encrypted export rather than copying another host's entire config or runtime state.

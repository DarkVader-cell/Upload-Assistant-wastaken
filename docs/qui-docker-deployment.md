# Qui Docker Deployment

This checkout is the drop-in Upload Assistant replacement used by the local
Qui instance.

## Persistent WebUI

Run from the repository root:

```bash
cd /home/artemis/Upload-Assistant-wastaken
./scripts/update-docker.sh
```

The script switches to `main`, fast-forwards from GitHub, pulls the published
Wastaken image, and recreates only the Upload Assistant service in `/opt/yams`
using `--no-deps`, leaving the shared VPN and torrent clients running.
The bind-mounted `docker-data/` directories and `/mnt/seeding` remain in place.
Confirm the service is `healthy` before resuming unattended Qui jobs.

Useful maintenance commands:

```bash
docker compose --env-file /opt/yams/.env -f /opt/yams/docker-compose.yaml logs --tail 200 -f upload-assistant
docker compose --env-file /opt/yams/.env -f /opt/yams/docker-compose.yaml restart upload-assistant
docker compose --env-file /opt/yams/.env -f /opt/yams/docker-compose.yaml down upload-assistant
```

`docker compose down` stops/removes the container but does not remove the
bind-mounted local state.

The canonical Compose file keeps the WebUI permanently active through
`gluetun_seeding` and persists:

- `docker-data/data` — `config.py`, caches, searchable release history, and application state;
- `docker-data/tmp` — logs, screenshots, queue state, and Qui job manifests;
- `docker-data/webui-auth` — WebUI sessions and authentication state;
- `/mnt/seeding` — the only host content root exposed to the WebUI.

Everything owned by Upload Assistant that must survive a rebuild or move is
under `docker-data/`; the folder is intentionally ignored by Git because it
contains configuration, cookies, WebUI credentials, session keys, audit logs,
and generated media/cache files. In particular:

- `docker-data/data/config.py` contains the active Upload Assistant settings;
- `docker-data/data/cookies/` contains tracker cookies;
- `docker-data/tmp/` contains generated descriptions, screenshots, logs, and
  the durable unattended-job state;
- `docker-data/webui-auth/` contains WebUI authentication and session data.

Do not commit or publicly upload `docker-data/`. It contains secrets.

## Syncing configuration to another client

For a new independent client, use [one-click installation](one-click-install.md)
and [selected encrypted config bundles](config-bundles.md). This preserves the
destination's paths and client mappings, and does not clone sessions, SSH private
keys, or submission/return state. Never use a full runtime copy as routine
configuration/key synchronization.

### Offline replacement-host migration only

The following full-state copy is for replacing an instance on a host with the
same intended identity and path layout, not adding another active client.
Stop all uploads and the service before taking a consistent copy, then sync the
complete folder to the same relative location in the other checkout:

```bash
cd /home/artemis/Upload-Assistant-wastaken
docker compose stop
rsync -aH --numeric-ids docker-data/ user@other-host:/path/to/Upload-Assistant-wastaken/docker-data/
docker compose start
```

On the destination, clone the repository, place the copied folder at
`docker-data/`, ensure `/mnt/seeding` is mounted there, and run the normal
update/start commands. Preserve the files and permissions; do not use a Git
checkout to transfer this folder.

Qui's wrapper token is separate from Upload Assistant state and remains in
Qui's `/config/.ua-token`. When moving Qui as well, copy that file through the
Qui configuration backup or create a new Wastaken API token and update the
wrapper on the destination.

The service listens on port `5000` inside the Gluetun network namespace, so
Qui reaches it through the existing `172.60.0.1:5000` route.

## Qui External Programs

The local Qui external program uses `/config/ua-submit` with the local UA
token. Its argument template should be `{content_path}` so the wrapper's
safe default selects the active `qbitt2` client and unattended mode. The
Whatbox entry uses `/config/ua-submit-whatbox`, posts to the Whatbox WebUI,
and reads `/config/.ua-token-whatbox`.

For the Whatbox qBittorrent instance, the external-program path mapping must
rewrite the qBittorrent host path `/home/artemisprime` to the path seen
by the Whatbox Upload Assistant container, `/mnt/seeding`. Its argument
template is `{content_path} -client qbittorrent`; the submit API appends
unattended mode by default and the wrapper supplies the session prefix.
Destiny's physical `/mnt/mpathf/artemisprime` prefix must also map to
`/mnt/seeding`. Local wrappers should use the stable host gateway
`http://172.60.0.1:5000`, not an ephemeral container IP.

The Clementine entry uses `/config/ua-submit-clementine`, the separate
`/config/.ua-token-clementine`, and the `qui.richmayfly.box.ca` Upload
Assistant endpoint. Its argument template is `{content_path} -client
qbittorrent`, matching Clementine's active qBittorrent profile. The two
Clementine-to-Grape recovery entries use `/config/ua-handoff-clementine-now`
and `/config/ua-racing-handoff-clementine-now`; both must remain executable
and use `{content_path}`.

For dashboards or automation, use `/api/qui/events` with a persisted cursor for incremental updates, `/api/qui/summary` for low-cost counts, `/api/qui/retry` for validated bulk recovery, and `/api/release_history` for cross-restart release outcomes. `/api/qui/status` remains the authoritative live resynchronization snapshot. All endpoints use the same Upload Assistant API token policy as the submit wrapper.

No Qui database migration is required for normal installs. Existing external-
program entries can be edited in Qui's External Programs settings; historical
stale IPs in old logs are not active configuration.

## Branches

- `dev` is the testing/integration branch.
- `main` is the promoted stable branch.

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
Wastaken image, and recreates only the Upload Assistant service in `/opt/yams`.
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

- `docker-data/data` — `config.py`, caches, and application state;
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

## Syncing to another host

Stop the service before taking a consistent copy, then sync the complete
folder to the same relative location in the other checkout:

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

The existing Qui programs should continue to use `/config/ua-submit` with
their current path mappings. That wrapper posts to `/api/qui/submit`, adds
unattended mode, and reads the API token from `/config/.ua-token`.

No Qui database migration is required. Both existing external-program entries
already point to this wrapper; historical stale IPs in old logs are not active
configuration.

## Branches

- `dev` is the testing/integration branch.
- `main` is the promoted stable branch.

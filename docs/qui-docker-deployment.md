# Qui Docker Deployment

This checkout is the drop-in Upload Assistant replacement used by the local
Qui instance.

## Persistent WebUI

Run from the repository root:

```bash
docker compose up -d --build
```

The canonical Compose file keeps the WebUI permanently active through
`gluetun_seeding` and persists:

- `docker-data/data` — `config.py`, caches, and application state;
- `docker-data/tmp` — logs, screenshots, queue state, and Qui job manifests;
- `docker-data/webui-auth` — WebUI sessions and authentication state;
- `/mnt/seeding` — the only host content root exposed to the WebUI.

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
- `wastaken` is retained as the compatibility branch and upstream-sync target.
- `development` remains the upstream development synchronization branch.

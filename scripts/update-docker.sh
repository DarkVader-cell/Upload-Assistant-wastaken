#!/usr/bin/env bash
set -euo pipefail

repo_dir="${UA_REPO_DIR:-/home/artemis/Upload-Assistant-wastaken}"
compose_file="${UA_COMPOSE_FILE:-/opt/yams/docker-compose.yaml}"
env_file="${UA_COMPOSE_ENV:-/opt/yams/.env}"

cd "$repo_dir"
git switch main
git pull --ff-only origin main
docker compose --env-file "$env_file" -f "$compose_file" pull upload-assistant
docker compose --env-file "$env_file" -f "$compose_file" up -d --force-recreate upload-assistant
docker compose --env-file "$env_file" -f "$compose_file" ps upload-assistant

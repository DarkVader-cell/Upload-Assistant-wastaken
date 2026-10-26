#!/usr/bin/env bash
# Bootstrap a self-contained Upload Assistant instance on a new Linux host.
# Docker is the default because it needs no host Python toolchain or root access.
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

IMAGE_DEFAULT="ghcr.io/darkvader-cell/upload-assistant-wastaken:latest"
REPO_DEFAULT="https://github.com/DarkVader-cell/Upload-Assistant-wastaken.git"
MODE="docker"
INSTALL_DEPS=0
BUNDLE=""
BUNDLE_PASSPHRASE_FILE=""
BUNDLE_OVERWRITE=0
INSTALL_DIR="${HOME}/upload-assistant"
BROWSE_ROOT=""
WEBUI_PORT="5000"
PROWLARR_URL=""
PROWLARR_KEY_FILE=""
PROMPT_PROWLARR_KEY=0
START_SERVICE=1
FORCE_CONFIG=0
IMAGE="$IMAGE_DEFAULT"
REPO_URL="$REPO_DEFAULT"

usage() {
    cat <<'EOF'
Usage: install-instance.sh [options]

Create or update a self-contained Upload Assistant instance. Docker mode is the
recommended portable installation; standalone mode delegates dependency setup
to install-seedbox.sh.

Required:
  --browse-root PATH             Host directory containing media to browse/upload.

Options:
  --install-dependencies         Install Debian/Ubuntu prerequisites using root/sudo.
  --import-bundle PATH           Import encrypted selected settings before starting.
  --bundle-passphrase-file PATH  Private passphrase file; otherwise prompt securely.
  --bundle-overwrite             Replace existing selected PORTABLE bundle settings.
  --mode docker|standalone       Installation mode (default: docker).
  --install-dir PATH             Instance directory (default: ~/upload-assistant).
  --webui-port PORT              Host Web UI port in Docker mode (default: 5000).
  --image IMAGE                  Docker image (default: fork's latest image).
  --repo-url URL                 Repository for standalone mode.
  --prowlarr-url URL             Prowlarr base URL for credential fallback.
  --prowlarr-api-key-file PATH   File containing only the Prowlarr API key.
  --prompt-prowlarr-api-key      Prompt securely for the Prowlarr API key.
  --force-config                 Permit configuration changes in an existing instance.
  --no-start                     Write files but do not start Docker Compose.
  -h, --help                     Show this help.

The installer never puts a Prowlarr API key in Compose files, environment
files, shell history, or command-line arguments. It is written only to UA's
config.py, which is restricted to the installing user.
EOF
}

log() { printf '==> %s\n' "$1"; }
fail() { printf 'Error: %s\n' "$1" >&2; exit 1; }
require_command() { command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"; }

while [ "$#" -gt 0 ]; do
    case "$1" in
        --install-dependencies) INSTALL_DEPS=1; shift ;;
        --import-bundle) BUNDLE="${2:?--import-bundle requires a path}"; shift 2 ;;
        --bundle-passphrase-file) BUNDLE_PASSPHRASE_FILE="${2:?--bundle-passphrase-file requires a path}"; shift 2 ;;
        --bundle-overwrite) BUNDLE_OVERWRITE=1; shift ;;
        --mode) MODE="${2:?--mode requires a value}"; shift 2 ;;
        --install-dir) INSTALL_DIR="${2:?--install-dir requires a path}"; shift 2 ;;
        --browse-root) BROWSE_ROOT="${2:?--browse-root requires a path}"; shift 2 ;;
        --webui-port) WEBUI_PORT="${2:?--webui-port requires a port}"; shift 2 ;;
        --image) IMAGE="${2:?--image requires an image}"; shift 2 ;;
        --repo-url) REPO_URL="${2:?--repo-url requires a URL}"; shift 2 ;;
        --prowlarr-url) PROWLARR_URL="${2:?--prowlarr-url requires a URL}"; shift 2 ;;
        --prowlarr-api-key-file) PROWLARR_KEY_FILE="${2:?--prowlarr-api-key-file requires a path}"; shift 2 ;;
        --prompt-prowlarr-api-key) PROMPT_PROWLARR_KEY=1; shift ;;
        --force-config) FORCE_CONFIG=1; shift ;;
        --no-start) START_SERVICE=0; shift ;;
        -h|--help) usage; exit 0 ;;
        *) fail "Unknown option: $1" ;;
    esac
done

case "$MODE" in docker|standalone) ;; *) fail "--mode must be docker or standalone" ;; esac
[ -n "$BROWSE_ROOT" ] || fail "--browse-root is required"
[ -d "$BROWSE_ROOT" ] || fail "Browse root does not exist or is not a directory: $BROWSE_ROOT"
case "$WEBUI_PORT" in *[!0-9]*|"") fail "--webui-port must be numeric" ;; esac
[ "$WEBUI_PORT" -ge 1 ] 2>/dev/null && [ "$WEBUI_PORT" -le 65535 ] 2>/dev/null || fail "--webui-port must be between 1 and 65535"
if [ -n "$PROWLARR_URL" ] && [ -z "$PROWLARR_KEY_FILE" ] && [ "$PROMPT_PROWLARR_KEY" -ne 1 ]; then
    fail "Prowlarr URL requires --prowlarr-api-key-file or --prompt-prowlarr-api-key"
fi
if [ -z "$PROWLARR_URL" ] && { [ -n "$PROWLARR_KEY_FILE" ] || [ "$PROMPT_PROWLARR_KEY" -eq 1 ]; }; then
    fail "A Prowlarr API key requires --prowlarr-url"
fi
if [ "$PROMPT_PROWLARR_KEY" -eq 1 ] && [ -n "$PROWLARR_KEY_FILE" ]; then
    fail "Use either --prompt-prowlarr-api-key or --prowlarr-api-key-file, not both"
fi

if [ "$INSTALL_DEPS" -eq 1 ]; then
    [ -r /etc/os-release ] || fail "Cannot detect operating system"
    source /etc/os-release
    case "${ID:-}" in debian|ubuntu) ;; *) fail "Automatic dependencies support Debian/Ubuntu only" ;; esac
    privilege=()
    if [ "$(id -u)" -ne 0 ]; then require_command sudo; privilege=(sudo); fi
    "${privilege[@]}" apt-get update
    packages=(git ca-certificates curl python3 python3-venv ffmpeg)
    if [ "$MODE" = docker ]; then
        compose_package=""
        for candidate in docker-compose-v2 docker-compose-plugin; do
            if apt-cache show "$candidate" >/dev/null 2>&1; then compose_package="$candidate"; break; fi
        done
        [ -n "$compose_package" ] || fail "No Compose v2 package in configured repositories; configure Docker's official repository first"
        packages+=(docker.io "$compose_package")
    else
        packages+=(build-essential libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev libffi-dev liblzma-dev libncurses-dev xz-utils)
    fi
    "${privilege[@]}" apt-get install -y "${packages[@]}"
    if [ "$MODE" = docker ]; then "${privilege[@]}" systemctl enable --now docker; fi
fi
if [ -n "$BUNDLE_PASSPHRASE_FILE" ] && [ -z "$BUNDLE" ]; then fail "--bundle-passphrase-file requires --import-bundle"; fi
if [ "$BUNDLE_OVERWRITE" -eq 1 ] && [ -z "$BUNDLE" ]; then fail "--bundle-overwrite requires --import-bundle"; fi

INSTALL_DIR="$(mkdir -p "$INSTALL_DIR" && cd "$INSTALL_DIR" && pwd)"
BROWSE_ROOT="$(cd "$BROWSE_ROOT" && pwd)"
KEY_TEMP=""
cleanup() { [ -z "$KEY_TEMP" ] || rm -f "$KEY_TEMP"; }
trap cleanup EXIT

if [ "$PROMPT_PROWLARR_KEY" -eq 1 ]; then
    KEY_TEMP="$(mktemp)"
    chmod 600 "$KEY_TEMP"
    printf 'Prowlarr API key: ' >&2
    IFS= read -r -s prowlarr_key
    printf '\n' >&2
    [ -n "$prowlarr_key" ] || fail "Prowlarr API key cannot be empty"
    printf '%s' "$prowlarr_key" >"$KEY_TEMP"
    unset prowlarr_key
    PROWLARR_KEY_FILE="$KEY_TEMP"
elif [ -n "$PROWLARR_KEY_FILE" ]; then
    [ -r "$PROWLARR_KEY_FILE" ] || fail "Cannot read Prowlarr API key file: $PROWLARR_KEY_FILE"
fi

configure_config() {
    local app_dir="$1" python_bin="$2" state_dir="${3:-$1}"
    local config_path="$state_dir/data/config.py"
    local template="$app_dir/data/example_config.py"
    [ -f "$template" ] || fail "Bundled example config is missing: $template"
    mkdir -p "$state_dir/data"
    if [ ! -f "$config_path" ]; then
        log "Creating initial configuration"
        cp "$template" "$config_path"
        chmod 600 "$config_path"
    elif [ "$FORCE_CONFIG" -ne 1 ] && { [ -n "$PROWLARR_URL" ] || [ -n "$PROWLARR_KEY_FILE" ]; }; then
        fail "Refusing to alter existing config.py without --force-config"
    fi

    # Synchronize schema first so older config files gain the Prowlarr fields
    # before the narrow update below. This preserves user-selected values.
    PYTHONPATH="$app_dir${PYTHONPATH:+:$PYTHONPATH}" "$python_bin" - "$config_path" "$template" <<'PY'
import sys
from pathlib import Path
from src.config_sync import sync_user_config
sync_user_config(Path(sys.argv[1]), Path(sys.argv[2]))
PY

    if [ -n "$PROWLARR_URL" ]; then
        PYTHONPATH="$app_dir${PYTHONPATH:+:$PYTHONPATH}" "$python_bin" - "$config_path" "$PROWLARR_URL" "$PROWLARR_KEY_FILE" <<'PY'
import ast
import os
import shutil
import stat
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

path = Path(sys.argv[1])
url = sys.argv[2]
key_file = Path(sys.argv[3])
key = key_file.read_text(encoding='utf-8').strip()
if not key:
    raise SystemExit('Prowlarr API key file is empty')
source = path.read_text(encoding='utf-8')
tree = ast.parse(source, filename=str(path))
assignment = next(node for node in tree.body if (isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'config' for target in node.targets)) or (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == 'config'))
default = next(value for key_node, value in zip(assignment.value.keys, assignment.value.values, strict=False) if isinstance(key_node, ast.Constant) and key_node.value == 'DEFAULT' and isinstance(value, ast.Dict))
entries = {key_node.value: value for key_node, value in zip(default.keys, default.values, strict=False) if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str)}
for required in ('prowlarr_url', 'prowlarr_api_key'):
    if required not in entries:
        raise SystemExit(f'Missing {required} after schema synchronization')
lines = source.splitlines(keepends=True)
def offset(node, end=False):
    line = node.end_lineno if end else node.lineno
    column = node.end_col_offset if end else node.col_offset
    return sum(len(item) for item in lines[:line - 1]) + column
edits = [(offset(entries['prowlarr_url']), offset(entries['prowlarr_url'], True), repr(url)), (offset(entries['prowlarr_api_key']), offset(entries['prowlarr_api_key'], True), repr(key))]
updated = source
for start, end, value in sorted(edits, reverse=True):
    updated = updated[:start] + value + updated[end:]
stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
backup = path.with_name(f'{path.name}.backup-prowlarr-{stamp}')
shutil.copy2(path, backup)
fd, temporary = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
try:
    with os.fdopen(fd, 'w', encoding='utf-8', newline='') as handle:
        handle.write(updated)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
    os.replace(temporary, path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
print(f'Configured Prowlarr credential fallback; backup: {backup.name}')
PY
    fi
}

import_bundle() {
    local python_bin="$1" config_path="$2"
    [ -n "$BUNDLE" ] || return 0
    local bundle_script="$SCRIPT_DIR/config-bundle.py"
    [ -f "$bundle_script" ] || fail "Run this installer from a checkout containing scripts/config-bundle.py"
    local args=(import --config "$config_path" --bundle "$BUNDLE")
    if [ "$BUNDLE_OVERWRITE" -eq 1 ]; then args+=(--overwrite); fi
    if [ -n "$BUNDLE_PASSPHRASE_FILE" ]; then args+=(--passphrase-file "$BUNDLE_PASSPHRASE_FILE"); fi
    "$python_bin" "$bundle_script" "${args[@]}"
}

install_docker() {
    require_command docker
    require_command python3
    python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' || fail "Bootstrap requires Python 3.11 or newer"
    docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is required"
    mkdir -p "$INSTALL_DIR/data" "$INSTALL_DIR/tmp" "$INSTALL_DIR/webui-auth"
    local app_dir="$INSTALL_DIR/bootstrap"
    if [ ! -d "$app_dir/.git" ]; then
        require_command git
        log "Cloning configuration template source"
        git clone --depth 1 "$REPO_URL" "$app_dir"
    else
        log "Updating configuration template source"
        git -C "$app_dir" pull --ff-only
    fi
    if [ -f "$INSTALL_DIR/data/config.py" ]; then
        log "Preserving existing instance configuration"
        cp "$INSTALL_DIR/data/config.py" "$app_dir/data/config.py"
        cp -a "$INSTALL_DIR/data/config.py" "$INSTALL_DIR/data/config.py.backup-installer-$(date -u +%Y%m%dT%H%M%SZ)"
    fi
    configure_config "$app_dir" python3
    cp "$app_dir/data/config.py" "$INSTALL_DIR/data/config.py"
    chmod 600 "$INSTALL_DIR/data/config.py"
    if [ -n "$BUNDLE" ]; then
        python3 -m venv "$INSTALL_DIR/.bootstrap-venv"
        "$INSTALL_DIR/.bootstrap-venv/bin/python" -m pip install 'cryptography==50.0.0'
        import_bundle "$INSTALL_DIR/.bootstrap-venv/bin/python" "$INSTALL_DIR/data/config.py"
    fi
    cat >"$INSTALL_DIR/.env" <<EOF
UA_IMAGE=$IMAGE
UA_STATE_DIR=$INSTALL_DIR
UA_BROWSE_ROOT=$BROWSE_ROOT
UA_WEBUI_PORT=$WEBUI_PORT
UA_PUID=$(id -u)
UA_PGID=$(id -g)
EOF
    cat >"$INSTALL_DIR/docker-compose.yml" <<'EOF'
services:
  upload-assistant:
    image: ${UA_IMAGE}
    restart: unless-stopped
    ports:
      - "${UA_WEBUI_PORT}:5000"
    command: ["--webui", "0.0.0.0:5000"]
    environment:
      PUID: "${UA_PUID}"
      PGID: "${UA_PGID}"
      UA_BROWSE_ROOTS: "/data"
      TMPDIR: "/state/tmp"
      MPLCONFIGDIR: "/state/tmp/matplotlib"
      XDG_CACHE_HOME: "/state/tmp/.cache"
    volumes:
      - "${UA_STATE_DIR}/data:/state/data:rw"
      - "${UA_STATE_DIR}/tmp:/state/tmp:rw"
      - "${UA_STATE_DIR}/webui-auth:/root/.config/upload-assistant:rw"
      - "${UA_BROWSE_ROOT}:/data:rw"
    healthcheck:
      test: ["CMD-SHELL", "code=$$(curl -sS -o /dev/null -w '%{http_code}' http://localhost:5000/api/health || true); test \"$$code\" -ge 200 -a \"$$code\" -lt 500"]
      interval: 30s
      timeout: 5s
      start_period: 15s
      retries: 3
EOF
    if [ "$START_SERVICE" -eq 1 ]; then
        log "Starting Upload Assistant"
        docker compose --env-file "$INSTALL_DIR/.env" -f "$INSTALL_DIR/docker-compose.yml" up -d
    fi
}

install_standalone() {
    local app_dir="$INSTALL_DIR/app"
    bash "$SCRIPT_DIR/install-seedbox.sh" --ua-dir "$app_dir" --repo-url "$REPO_URL"
    configure_config "$app_dir" "$app_dir/.venv/bin/python" "$INSTALL_DIR"
    import_bundle "$app_dir/.venv/bin/python" "$INSTALL_DIR/data/config.py"
    cat >"$INSTALL_DIR/run-ua.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
INSTANCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export UA_DATA_DIR="$INSTANCE_DIR"
exec "$INSTANCE_DIR/app/run-ua.sh" "$@"
EOF
    chmod +x "$INSTALL_DIR/run-ua.sh"
    log "Standalone runner: $INSTALL_DIR/run-ua.sh '$BROWSE_ROOT' --webui 0.0.0.0:$WEBUI_PORT"
}

case "$MODE" in
    docker) install_docker ;;
    standalone) install_standalone ;;
esac

cat <<EOF

Installation complete.

Instance directory: $INSTALL_DIR
Browse root in the container: /data
Web UI: http://localhost:$WEBUI_PORT

Prowlarr credential fallback is $( [ -n "$PROWLARR_URL" ] && printf 'configured' || printf 'not configured' ).
Enable the desired Prowlarr indexers; Upload Assistant will use supported
credentials only when corresponding local tracker credentials are absent.
EOF

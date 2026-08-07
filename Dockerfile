# syntax=docker/dockerfile:1.7

ARG PYTHON_IMAGE=python:3.14-slim

# Build Python packages away from the runtime image. Native dependencies must
# provide wheels for both published architectures; pure-Python source packages
# can still build without downloading a compiler toolchain.
FROM ${PYTHON_IMAGE} AS python-deps

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_INPUT=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"

RUN python -m venv "${VIRTUAL_ENV}"
COPY --link requirements.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    python -m pip install --upgrade pip==25.3 wheel==0.45.1 \
    && python -m pip install --prefer-binary -r /tmp/requirements.txt \
    && python -m pip check \
    && find "${VIRTUAL_ENV}" -type d -name __pycache__ -prune -exec rm -rf '{}' + \
    && find "${VIRTUAL_ENV}" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

# Binary downloads have their own stable stages, so changing application source
# or Python requirements does not force another download.
FROM ${PYTHON_IMAGE} AS binary-fetch-base

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_INPUT=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /Upload-Assistant
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    python -m pip install requests==2.33.0 aiofiles==25.1.0 httpx==0.28.1

FROM binary-fetch-base AS dvd-mediainfo
COPY --link bin/get_dvd_mediainfo_docker.py bin/
RUN python bin/get_dvd_mediainfo_docker.py

FROM binary-fetch-base AS mkbrr
COPY --link bin/__init__.py bin/get_mkbrr.py bin/
RUN python -c "from bin.get_mkbrr import MkbrrBinaryManager; MkbrrBinaryManager.download_mkbrr_for_docker()"

FROM binary-fetch-base AS bdinfo
COPY --link bin/get_bdinfo_docker.py bin/
RUN python bin/get_bdinfo_docker.py

# The final image contains only the runtime interpreter, application, downloaded
# helper binaries, and packages that are required while Upload Assistant runs.
FROM ${PYTHON_IMAGE} AS runtime

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        ffmpeg \
        gosu \
        mediainfo \
    && update-ca-certificates

ENV MPLCONFIGDIR=/Upload-Assistant/tmp/matplotlib \
    TMPDIR=/Upload-Assistant/tmp \
    XDG_CACHE_HOME=/Upload-Assistant/tmp/.cache

WORKDIR /Upload-Assistant

COPY --from=python-deps --link /opt/venv /opt/venv
COPY --link upload.py config-generator.py requirements.txt LICENSE README.md ./
COPY --link cogs ./cogs
COPY --link --chown=1000:1000 data ./data
COPY --link src ./src
COPY --link web_ui ./web_ui
COPY --link --chown=1000:1000 bin ./bin

# Overlay only the binary matching the target architecture. Multi-platform
# builds therefore do not carry binaries for every supported architecture.
COPY --from=dvd-mediainfo --link --chown=1000:1000 /Upload-Assistant/bin/MI/linux ./bin/MI/linux
COPY --from=mkbrr --link --chown=1000:1000 /Upload-Assistant/bin/mkbrr ./bin/mkbrr
COPY --from=bdinfo --link --chown=1000:1000 /Upload-Assistant/bin/bdinfo ./bin/bdinfo

COPY --link --chmod=755 scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY --link --chmod=755 scripts/docker-healthcheck.py /usr/local/bin/upload-assistant-healthcheck

# Keep defaults outside the data mount and make writable paths usable by both
# the normal UID and NAS/Unraid PUID/PGID configurations.
RUN set -eux; \
    mkdir -p defaults tmp; \
    cp -a data defaults/; \
    find defaults -type d -name __pycache__ -prune -exec rm -rf '{}' +; \
    chmod 1777 tmp

EXPOSE 5000
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["upload-assistant-healthcheck"]

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["-h"]

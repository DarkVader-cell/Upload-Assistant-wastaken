#!/usr/bin/env python3
"""Dependency-free Docker health check for the Upload Assistant Web UI."""

from __future__ import annotations

import os
import sys
from urllib.error import URLError
from urllib.request import urlopen


def main() -> int:
    url = os.environ.get("UA_HEALTHCHECK_URL", "http://127.0.0.1:5000/api/health")
    try:
        with urlopen(url, timeout=4) as response:  # noqa: S310 - URL is operator-controlled
            if 200 <= response.status < 300:
                return 0
            print(f"Health check returned HTTP {response.status}", file=sys.stderr)
    except (OSError, URLError) as exc:
        print(f"Health check failed: {exc}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

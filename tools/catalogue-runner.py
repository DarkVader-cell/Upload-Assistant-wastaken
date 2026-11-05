#!/usr/bin/env python3
"""Run from the CardinalDL host; no SSH credentials or remote shell commands."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.catalogue_runner import main

if __name__ == "__main__":
    raise SystemExit(main())

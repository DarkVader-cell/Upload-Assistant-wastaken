"""Policy helpers for unattended queue operations."""

from collections.abc import Mapping
from typing import Any


def should_prompt_for_queue_edits(meta: Mapping[str, Any]) -> bool:
    """Return whether queue creation or update may request interactive input."""
    return not bool(meta.get("unattended")) or bool(meta.get("unattended_confirm"))

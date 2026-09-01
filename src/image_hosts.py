"""Runtime availability rules for image hosts."""

from typing import Any

# Imgbox is currently unavailable. Keep it out of automatic selection and
# fallback chains until it is reliable again.
DISABLED_IMAGE_HOSTS = frozenset({"imgbox"})


def is_enabled_image_host(value: Any) -> bool:
    """Return whether an image host is currently usable by Upload Assistant."""
    return isinstance(value, str) and value.strip().lower() not in DISABLED_IMAGE_HOSTS

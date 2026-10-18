"""Validate HDB image-host responses before publishing screenshot BBCode."""
import io
import re
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from src.runtime.http import shared_http_client
from src.safe_url import assert_public_http_url

_PATTERN = r"(?:\[url=(https://[^\s\[\]]+)\])?\[img\](https://[^\s\[\]]+)\[/img\](?(1)\[/url\])"


def image_count(value: str) -> int:
    return len(list(re.finditer(_PATTERN, value, flags=re.IGNORECASE)))


def validate_image_bbcode(value: str | None, *, columns: int = 2, expected: int | None = None) -> str:
    """Accept complete exact-host HDB BBCode, never HTML/JSON error responses."""
    if not value:
        raise ValueError("HDB image upload failed or returned no BBCode")
    matches = list(re.finditer(_PATTERN, value, flags=re.IGNORECASE))
    if not matches or re.sub(_PATTERN, "", value, flags=re.IGNORECASE).strip():
        raise ValueError("HDB image upload returned unexpected BBCode")
    if expected is not None and len(matches) != expected:
        raise ValueError("HDB image upload returned an incomplete screenshot batch")
    for match in matches:
        for url in match.groups():
            if url is None:
                continue
            if any(ord(char) < 33 or ord(char) > 126 or char in "\"'<>\\" for char in url):
                raise ValueError("HDB image upload returned an unsafe URL")
            parts = urlsplit(url)
            if parts.scheme != "https" or parts.netloc not in {"img.hdbits.org", "t.hdbits.org"} or not parts.path.startswith("/") or parts.path == "/":
                raise ValueError("HDB image upload returned a non-HDB image/gallery URL")
    columns = max(1, columns)
    thumbnails = [match.group() for match in matches]
    return "\n".join(" ".join(thumbnails[i:i + columns]) for i in range(0, len(thumbnails), columns))


async def recover_hosted_images(directory: Path, images: list[dict[str, Any]], limit: int) -> list[Path]:
    """Recover full-size screenshots reused from a prior run, never gallery thumbnails.

    Every redirect is revalidated, the body is bounded, and invalid/non-image
    content cannot be sent onward to HDB's image API. Offer mode never calls this.
    """
    from PIL import Image

    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    recovered: list[Path] = []
    for image in images[:limit]:
        url = image.get("raw_url")
        if not isinstance(url, str) or not url:
            continue
        try:
            async with shared_http_client("hdb-image-recovery", request_timeout=30, follow_redirects=False, factory=httpx.AsyncClient) as client:
                for _ in range(4):
                    parsed = urlsplit(url)
                    if parsed.username is not None or parsed.password is not None or len(url) > 8192:
                        raise ValueError("Image URLs must not contain credentials")
                    await assert_public_http_url(url)
                    async with client.stream("GET", url) as response:
                        if response.is_redirect:
                            location = response.headers.get("location")
                            if not location:
                                raise ValueError("Missing redirect target")
                            url = str(response.url.join(location))
                            continue
                        response.raise_for_status()
                        content = bytearray()
                        async for block in response.aiter_bytes():
                            content.extend(block)
                            if len(content) > 32 * 1024 * 1024:
                                raise ValueError("Screenshot download exceeds safety limit")
                        break
                else:
                    raise ValueError("Too many image redirects")
            with Image.open(io.BytesIO(content)) as decoded:
                if decoded.width * decoded.height > 40000000:
                    raise ValueError("Screenshot dimensions exceed safety limit")
                decoded.verify()
            with Image.open(io.BytesIO(content)) as decoded:
                path = directory / (secrets.token_hex(16) + ".png")
                with path.open("xb") as output:
                    path.chmod(0o600)
                    if decoded.format == "PNG":
                        output.write(content)
                    else:
                        decoded.convert("RGB").save(output, format="PNG")
            recovered.append(path)
        except (httpx.HTTPError, OSError, ValueError, Image.DecompressionBombError):
            continue
    return recovered

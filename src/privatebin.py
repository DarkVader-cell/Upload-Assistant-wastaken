"""Minimal PrivateBin v2 writer: only ciphertext leaves this process."""

from __future__ import annotations

import base64
import json
import re
import secrets
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from src.runtime.http import shared_http_client
from src.safe_url import assert_public_http_url

DEFAULT_ENDPOINT = "https://privatebin.net/"
_BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


class PrivateBinError(ValueError):
    """A sanitized failure, safe to display without response bodies or secrets."""


def _base58(value: bytes) -> str:
    number = int.from_bytes(value, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = _BASE58[remainder] + encoded
    return "1" * (len(value) - len(value.lstrip(b"\0"))) + encoded


async def _endpoint(value: str) -> str:
    try:
        if not isinstance(value, str):
            raise ValueError("Invalid endpoint")
        parts = urlsplit(value)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or "?" in value
            or "#" in value
            or any(ord(char) <= 32 or ord(char) >= 127 or char in "\\%" for char in value)
        ):
            raise ValueError("Invalid endpoint")
        await assert_public_http_url(value)
    except (ValueError, OSError):
        raise PrivateBinError("PrivateBin endpoint must be a public HTTPS URL without credentials, query or fragment") from None
    return value


async def create_paste(text: str, endpoint: str = DEFAULT_ENDPOINT) -> str:
    """Return a secret share URL; its Base58 key is never included in the POST.

    PrivateBin's v2 format authenticates the compact JSON adata array, and
    derives the AES key from the *raw* random bytes, not their Base58 spelling.
    https://github.com/PrivateBin/PrivateBin/wiki/Encryption-format
    """
    endpoint = await _endpoint(endpoint)
    key, iv, salt = secrets.token_bytes(32), secrets.token_bytes(16), secrets.token_bytes(8)
    adata = [[base64.b64encode(iv).decode("ascii"), base64.b64encode(salt).decode("ascii"), 100000, 256, 128, "aes", "gcm", "none"], "plaintext", 0, 0]
    aad = json.dumps(adata, separators=(",", ":")).encode("utf-8")
    plaintext = json.dumps({"paste": text}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    derived_key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000).derive(key)
    ciphertext = AESGCM(derived_key).encrypt(iv, plaintext, aad)
    payload = {"v": 2, "adata": adata, "ct": base64.b64encode(ciphertext).decode("ascii"), "meta": {"expire": "1week"}}
    try:
        async with shared_http_client("privatebin", request_timeout=30, follow_redirects=False, factory=httpx.AsyncClient) as client:
            response = await client.post(endpoint, json=payload, headers={"X-Requested-With": "JSONHttpRequest"})
        if response.status_code != 200:
            raise ValueError("Unexpected HTTP status")
        result = response.json()
        if (
            not isinstance(result, dict)
            or type(result.get("status")) is not int
            or result["status"] != 0
            or not isinstance(result.get("id"), str)
            or re.fullmatch(r"[0-9a-fA-F]{16}", result["id"]) is None
        ):
            raise ValueError("Invalid paste response")
    except (httpx.HTTPError, ValueError):
        # Neither server messages nor transport exceptions are safe to echo.
        raise PrivateBinError("Encrypted PrivateBin upload failed") from None
    return f"{endpoint}?{result['id']}#{_base58(key)}"

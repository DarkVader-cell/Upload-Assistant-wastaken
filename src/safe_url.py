from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeURL(ValueError):
    """Raised when a URL points at a disallowed local/private network target."""


def _blocked_ip(ip: str) -> bool:
    address = ipaddress.ip_address(ip)
    return address.is_private or address.is_loopback or address.is_link_local or address.is_multicast or address.is_reserved or address.is_unspecified


async def assert_public_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise UnsafeURL("Only http/https image URLs are allowed")
    host = parsed.hostname
    if not host:
        raise UnsafeURL("URL hostname is missing")
    if host.lower() == "localhost" or host.lower().endswith(".localhost"):
        raise UnsafeURL("Localhost URLs are not allowed")
    try:
        if _blocked_ip(host):
            raise UnsafeURL("Private or reserved IP URLs are not allowed")
    except ValueError as error:
        if isinstance(error, UnsafeURL):
            raise
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, parsed.port or (443 if parsed.scheme.lower() == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise UnsafeURL(f"Could not resolve URL hostname: {host}") from error
    for info in infos:
        if _blocked_ip(info[4][0]):
            raise UnsafeURL("URL resolves to a private or reserved IP")


async def public_http_url(url: str) -> bool:
    try:
        await assert_public_http_url(url)
        return True
    except UnsafeURL:
        return False

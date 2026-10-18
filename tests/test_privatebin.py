"""PrivateBin v2 interoperability and failure isolation; no real network calls."""

import base64
import hashlib
import json
import socket
from urllib.parse import urlsplit

import httpx
import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from src import privatebin
from src.privatebin import PrivateBinError, create_paste


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected real network access")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])


@pytest.fixture
def transport(monkeypatch):
    original = httpx.AsyncClient
    requests = []
    def install(handler):
        def capture(request):
            requests.append(request)
            return handler(request)
        def client(**kwargs):
            assert kwargs["follow_redirects"] is False
            assert kwargs["verify"] is True
            return original(transport=httpx.MockTransport(capture), **kwargs)
        monkeypatch.setattr(privatebin.httpx, "AsyncClient", client)
        return requests
    return install


def decode_base58(value):
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number = 0
    for char in value:
        number = number * 58 + alphabet.index(char)
    raw = number.to_bytes((number.bit_length() + 7) // 8, "big")
    return b"\0" * (len(value) - len(value.lstrip("1"))) + raw


@pytest.mark.parametrize("random_key", [bytes(range(32)), b"\0\0" + bytes(range(2, 32)), b"\xff" * 32])
@pytest.mark.asyncio
async def test_privatebin_v2_outgoing_payload_decrypts_independently(transport, monkeypatch, random_key, capsys):
    values = iter([random_key, bytes(range(16)), bytes(range(8))])
    monkeypatch.setattr(privatebin.secrets, "token_bytes", lambda size: next(values))
    requests = transport(lambda request: httpx.Response(200, json={"status": 0, "id": "0123456789abcdef", "url": "https://evil.test/?spoof", "deletetoken": "ignored"}))
    text = "Title: Synthetic\nFORM:\nCategory: Movie\nDescription:\n[hide=MediaInfo]TEST ONLY café 雪[/hide]\n"
    link = await create_paste(text)
    assert link.startswith("https://privatebin.net/?0123456789abcdef#")
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://privatebin.net/" and request.method == "POST"
    assert request.headers["X-Requested-With"] == "JSONHttpRequest"
    assert request.headers["content-type"] == "application/json"
    payload = json.loads(request.content)
    assert set(payload) == {"v", "adata", "ct", "meta"}
    assert payload["v"] == 2 and payload["meta"] == {"expire": "1week"}
    assert isinstance(payload["adata"], list) and isinstance(payload["adata"][0], list)
    params, formatter, discussion, burn = payload["adata"]
    iv, salt, iterations, bits, tag_bits, algorithm, mode, compression = params
    iv, salt = base64.b64decode(iv), base64.b64decode(salt)
    assert (len(iv), len(salt), iterations, bits, tag_bits) == (16, 8, 100000, 256, 128)
    assert (algorithm, mode, compression, formatter, discussion, burn) == ("aes", "gcm", "none", "plaintext", 0, 0)
    key = decode_base58(urlsplit(link).fragment)
    assert key == random_key and len(key) == 32
    # Independent stdlib KDF and low-level GCM decryptor, not the writer helpers.
    derived = hashlib.pbkdf2_hmac("sha256", key, salt, iterations, dklen=bits // 8)
    ciphertext = base64.b64decode(payload["ct"])
    decryptor = Cipher(algorithms.AES(derived), modes.GCM(iv, ciphertext[-16:])).decryptor()
    decryptor.authenticate_additional_data(json.dumps(payload["adata"], separators=(",", ":")).encode())
    cleartext = decryptor.update(ciphertext[:-16]) + decryptor.finalize()
    assert json.loads(cleartext) == {"paste": text}
    assert text.encode() not in request.content
    assert b"Synthetic" not in request.content and b"TEST ONLY" not in request.content
    request_bytes = str(request.url).encode() + str(request.headers).encode() + request.content
    for secret in (key, base64.b64encode(key), key.hex().encode(), urlsplit(link).fragment.encode()):
        assert secret not in request_bytes
    assert capsys.readouterr().out == ""


@pytest.mark.asyncio
async def test_explicit_public_https_endpoint_preserves_path_ignores_response_url(transport):
    requests = transport(lambda request: httpx.Response(200, json={"status": 0, "id": "abcdef0123456789", "url": "http://evil.test/"}))
    link = await create_paste("synthetic", "https://paste.example/bin/")
    assert link.startswith("https://paste.example/bin/?abcdef0123456789#")
    assert str(requests[0].url) == "https://paste.example/bin/"


@pytest.mark.parametrize("endpoint", [
    "http://privatebin.net/", "file:///tmp/paste", "https://user:password@paste.example/",
    "https://user@paste.example/", "https://paste.example/?query", "https://paste.example/?",
    "https://paste.example/#key", "https://paste.example/#", "https://localhost/",
    "https://a.localhost/", "https://127.0.0.1/", "https://10.0.0.1/", "https://169.254.169.254/",
    "https://[::1]/", "https://[fc00::1]/", "https://0.0.0.0/", "https://paste.example/white space/",
    "https://paste.example/\\evil", "https://paste.example/%2f/", "https:///missing-host", None, 123,
])
@pytest.mark.asyncio
async def test_unsafe_endpoint_rejected_before_request(endpoint, transport):
    requests = transport(lambda request: pytest.fail("No request allowed"))
    with pytest.raises(PrivateBinError):
        await create_paste("synthetic", endpoint)
    assert requests == []


@pytest.mark.parametrize("address", ["192.168.1.2", "127.0.0.1", "::1", "fd00::1", "169.254.169.254", "224.0.0.1"])
@pytest.mark.asyncio
async def test_public_hostname_resolving_to_private_ip_rejected(address, monkeypatch, transport):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))])
    requests = transport(lambda request: pytest.fail("No request allowed"))
    with pytest.raises(PrivateBinError):
        await create_paste("synthetic", "https://paste.example/")
    assert requests == []


@pytest.mark.asyncio
async def test_dns_failure_is_sanitized(monkeypatch, transport):
    def fail(*args, **kwargs):
        raise socket.gaierror("secret resolver details")
    monkeypatch.setattr(socket, "getaddrinfo", fail)
    requests = transport(lambda request: pytest.fail("No request allowed"))
    with pytest.raises(PrivateBinError) as error:
        await create_paste("synthetic", "https://paste.example/")
    assert "secret" not in str(error.value)
    assert requests == []


@pytest.mark.parametrize("result", [
    {"status": 1, "message": "secret server error"}, {"status": "0", "id": "0123456789abcdef"},
    {"status": False, "id": "0123456789abcdef"}, {"id": "0123456789abcdef"},
    {"status": 0}, {"status": 0, "id": "0123456789abcde"},
    {"status": 0, "id": "0123456789abcdef0"}, {"status": 0, "id": "../?evil#secret"},
    {"status": 0, "id": 123}, [], None,
])
@pytest.mark.asyncio
async def test_invalid_responses_fail_once_without_fallback_or_response_leak(result, transport):
    requests = transport(lambda request: httpx.Response(200, json=result))
    with pytest.raises(PrivateBinError, match="Encrypted PrivateBin upload failed") as error:
        await create_paste("synthetic secret")
    assert "secret" not in str(error.value)
    assert len(requests) == 1


@pytest.mark.parametrize("status", [301, 302, 307, 308, 400, 403, 429, 500])
@pytest.mark.asyncio
async def test_redirect_and_http_failure_never_followed_or_retried(status, transport):
    requests = transport(lambda request: httpx.Response(status, headers={"Location": "https://evil.test/"}, text="secret body"))
    with pytest.raises(PrivateBinError):
        await create_paste("synthetic secret")
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_invalid_json_does_not_leak_response(transport):
    requests = transport(lambda request: httpx.Response(200, text="<html>secret error</html>"))
    with pytest.raises(PrivateBinError) as error:
        await create_paste("synthetic secret")
    assert "secret" not in str(error.value) and len(requests) == 1


@pytest.mark.asyncio
async def test_transport_failure_does_not_leak_or_retry(transport):
    def fail(request):
        raise httpx.ConnectError("secret transport details", request=request)
    requests = transport(fail)
    with pytest.raises(PrivateBinError) as error:
        await create_paste("synthetic secret")
    assert "secret" not in str(error.value) and len(requests) == 1

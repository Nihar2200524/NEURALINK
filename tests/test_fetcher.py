import gzip

import httpx
import pytest

from app.core.config import Settings
from app.core.exceptions import BridgeError
from app.services.fetcher import HTTPFetcher
from app.utils.urls import URLPolicy, normalize_url


class PublicPolicy(URLPolicy):
    async def resolve(self, url):
        url = normalize_url(url)
        if "example.com" in url:
            return url, "93.184.216.34"
        return await super().resolve(url)


class Stream(httpx.AsyncByteStream):
    def __init__(self, body):
        self.body = body

    async def __aiter__(self):
        yield self.body


def response(body=b"<p>Hello</p>", status=200, **headers):
    return httpx.Response(status, headers={"content-type": "text/html", **headers}, stream=Stream(body))


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "ftp://example.com", "http://u:p@example.com", "http://example.com:22"]
)
def test_invalid(url):
    with pytest.raises(BridgeError, match="HTTP"):
        normalize_url(url)


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "10.0.0.1", "169.254.169.254", "[::1]", "[::ffff:127.0.0.1]", "localhost", "100.64.0.1"],
)
async def test_ssrf(host):
    with pytest.raises(BridgeError) as error:
        await URLPolicy().resolve("http://" + host)
    assert error.value.code == "BLOCKED_URL"


async def test_pinning_and_compression():
    def handler(request):
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "example.com"
        assert request.extensions["sni_hostname"] == "example.com"
        return response(gzip.compress(b"hello"), **{"content-encoding": "gzip"})

    fetcher = HTTPFetcher(Settings(), PublicPolicy(), httpx.MockTransport(handler))
    try:
        assert (await fetcher.fetch("https://example.com")).html == "hello"
    finally:
        await fetcher.close()


async def test_public_redirect_and_origin_partition():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return response(status=302, location="https://other.example.com/final")
        return response()

    fetcher = HTTPFetcher(Settings(), PublicPolicy(), httpx.MockTransport(handler))
    try:
        result = await fetcher.fetch("https://example.com")
        assert result.url == "https://other.example.com/final"
        assert len(fetcher.clients) == 2
        assert calls[1].extensions["sni_hostname"] == "other.example.com"
        assert calls[1].headers["cookie"] == ""
    finally:
        await fetcher.close()


async def test_mixed_dns_blocks_all(monkeypatch):
    import asyncio

    async def resolve(*args, **kwargs):
        return [(2, 1, 6, "", ("93.184.216.34", 443)), (2, 1, 6, "", ("127.0.0.1", 443))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    with pytest.raises(BridgeError) as error:
        await URLPolicy().resolve("https://mixed.example")
    assert error.value.code == "BLOCKED_URL"


@pytest.mark.parametrize(
    "kind,code",
    [
        ("redirect", "BLOCKED_URL"),
        ("mime", "UNSUPPORTED_CONTENT_TYPE"),
        ("size", "CONTENT_TOO_LARGE"),
        ("timeout", "FETCH_TIMEOUT"),
        ("loop", "FETCH_FAILED"),
        ("bomb", "CONTENT_TOO_LARGE"),
    ],
)
async def test_failures(kind, code):
    def handler(request):
        if kind == "timeout":
            raise httpx.ReadTimeout("timeout")
        if kind in {"redirect", "loop"}:
            return response(status=302, location="http://127.0.0.1" if kind == "redirect" else "/loop")
        if kind == "mime":
            return response(**{"content-type": "image/png"})
        if kind == "bomb":
            return response(gzip.compress(b"x" * 10000), **{"content-encoding": "gzip"})
        return response(b"x" * 101)

    fetcher = HTTPFetcher(Settings(max_response_bytes=100), PublicPolicy(), httpx.MockTransport(handler))
    try:
        with pytest.raises(BridgeError) as error:
            await fetcher.fetch("https://example.com")
        assert error.value.code == code
    finally:
        await fetcher.close()

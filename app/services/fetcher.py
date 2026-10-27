import asyncio
import zlib
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from app.core.config import Settings
from app.core.exceptions import BridgeError
from app.utils.urls import URLPolicy


@dataclass
class FetchedDocument:
    url: str
    html: str
    raw_bytes: int
    content_type: str = "text/html"
    method: str = "http"
    status: int = 200
    cacheable: bool = True


class Fetcher(Protocol):
    async def fetch(self, url: str) -> FetchedDocument: ...


class HTTPFetcher:
    def __init__(
        self,
        settings: Settings,
        policy: URLPolicy | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.settings = settings
        self.policy = policy or URLPolicy()
        self.before_request = None
        self.slots = asyncio.Semaphore(settings.concurrency)
        self.transport = transport
        self.clients: dict[str, httpx.AsyncClient] = {}

    def _new_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self.transport,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(self.settings.timeout, connect=min(5, self.settings.timeout)),
            limits=httpx.Limits(max_connections=self.settings.concurrency, max_keepalive_connections=2),
            headers={"User-Agent": self.settings.user_agent, "Accept-Encoding": "gzip, deflate"},
        )

    @asynccontextmanager
    async def _stream(self, origin: str, target: str, hostname: str, authority: str):
        # Partition pools by original origin, never only by the pinned IP. Two virtual
        # hosts can share an IP but require distinct TLS hostname verification.
        client = self.clients.get(origin)
        temporary = client is None and len(self.clients) >= 32
        if client is None:
            client = self._new_client()
            if not temporary:
                self.clients[origin] = client
        try:
            async with client.stream(
                "GET",
                target,
                headers={"Host": authority, "Cookie": ""},
                extensions={"sni_hostname": hostname},
            ) as response:
                yield response
        finally:
            if temporary:
                await client.aclose()

    async def close(self) -> None:
        for client in self.clients.values():
            await client.aclose()

    async def fetch(self, url: str) -> FetchedDocument:
        return await self.retrieve(url, {"text/html", "application/xhtml+xml", "text/plain"})

    async def retrieve(
        self, url: str, allowed_types: set[str] | None, check_robots: bool = True, accept_errors: bool = False
    ) -> FetchedDocument:
        try:
            async with asyncio.timeout(self.settings.timeout):
                async with self.slots:
                    return await self._retrieve(url, allowed_types, check_robots, accept_errors)
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise BridgeError(
                "FETCH_TIMEOUT", "The target website did not respond before the timeout.", 504
            ) from exc
        except (httpx.HTTPError, zlib.error) as exc:
            raise BridgeError("FETCH_FAILED", "The target response could not be retrieved.", 502) from exc

    async def _retrieve(
        self, url: str, allowed_types: set[str] | None, check_robots: bool, accept_errors: bool
    ) -> FetchedDocument:
        for redirect in range(self.settings.max_redirects + 1):
            url, address = await self.policy.resolve(url)
            if check_robots and self.before_request:
                await self.before_request(url)
            parts = urlsplit(url)
            host = f"[{address}]" if ":" in address else address
            target = urlunsplit(
                (parts.scheme, host + (f":{parts.port}" if parts.port else ""), parts.path, parts.query, "")
            )
            async with self._stream(
                f"{parts.scheme}://{parts.netloc}", target, parts.hostname, parts.netloc
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    if redirect == self.settings.max_redirects:
                        raise BridgeError("FETCH_FAILED", "Redirect limit exceeded.", 502)
                    location = response.headers.get("location")
                    if not location:
                        raise BridgeError("FETCH_FAILED", "Redirect has no destination.", 502)
                    url = urljoin(url, location)
                    continue
                if response.status_code == 429:
                    raise BridgeError("RATE_LIMITED", "The target website rate limited the request.", 429)
                if response.status_code >= 400 and not accept_errors:
                    raise BridgeError("FETCH_FAILED", f"Target returned HTTP {response.status_code}.", 502)
                mime = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if allowed_types is not None and mime not in allowed_types:
                    raise BridgeError(
                        "UNSUPPORTED_CONTENT_TYPE", "The target is not HTML or plain text.", 415
                    )
                body, wire_size = await self._read(response)
                encoding = response.encoding or "utf-8"
                try:
                    html = body.decode(encoding, errors="replace")
                except LookupError:
                    html = body.decode("utf-8", errors="replace")
                control = response.headers.get("cache-control", "").lower()
                cacheable = not any(token in control for token in ("no-store", "no-cache", "private"))
                cacheable = cacheable and "set-cookie" not in response.headers
                return FetchedDocument(
                    url, html, wire_size, mime, status=response.status_code, cacheable=cacheable
                )
        raise AssertionError("Unreachable redirect state")

    async def _read(self, response: httpx.Response) -> tuple[bytes, int]:
        limit = self.settings.max_response_bytes
        length = response.headers.get("content-length", "")
        if length.isdigit() and int(length) > limit:
            raise BridgeError("CONTENT_TOO_LARGE", "Response exceeds the size limit.", 413)
        encoding = response.headers.get("content-encoding", "identity").lower().strip()
        if encoding not in {"identity", "gzip", "deflate"}:
            raise BridgeError("FETCH_FAILED", "Unsupported response compression.", 502)
        decoder = zlib.decompressobj(31 if encoding == "gzip" else 15) if encoding != "identity" else None
        output = bytearray()
        wire = 0
        async for chunk in response.aiter_raw(chunk_size=16384):
            wire += len(chunk)
            if wire > limit:
                raise BridgeError("CONTENT_TOO_LARGE", "Response exceeds the size limit.", 413)
            output.extend(decoder.decompress(chunk, limit + 1 - len(output)) if decoder else chunk)
            if len(output) > limit or (decoder and decoder.unconsumed_tail):
                raise BridgeError("CONTENT_TOO_LARGE", "Decoded response exceeds the size limit.", 413)
        if decoder and (not decoder.eof or decoder.unused_data):
            raise BridgeError("FETCH_FAILED", "Invalid or concatenated compressed response.", 502)
        return bytes(output), wire

"""Bounded local forward proxy with DNS validation at connection time.

TLS remains end-to-end: CONNECT relays bytes to a validated numeric IP.
An OS firewall is still required to contain a compromised browser process.
"""
import asyncio
import base64
import hmac
import secrets
from contextlib import suppress
from urllib.parse import urlsplit
from .security import resolve_public


class EgressProxy:
    def __init__(self) -> None:
        self.password = secrets.token_urlsafe(32)
        self.server: asyncio.Server | None = None
        self.tasks: set[asyncio.Task[None]] = set()
        self.address = ""
        self.closed = False

    async def start(self) -> None:
        self.server = await asyncio.start_server(self.accept, "127.0.0.1", 0, limit=32768)
        self.address = f"http://127.0.0.1:{self.server.sockets[0].getsockname()[1]}"

    def accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self.closed or len(self.tasks) >= 128:
            writer.close()
            return
        task = asyncio.create_task(self.handle(reader, writer))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def connect(self, host: str, port: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        addresses = await resolve_public(host, port)
        for address in addresses:
            try:
                # Numeric address avoids a second, attacker-controlled DNS lookup.
                return await asyncio.open_connection(address, port)
            except OSError:
                continue
        raise OSError("Upstream unavailable")

    async def pipe(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while chunk := await reader.read(65536):
            writer.write(chunk)
            await writer.drain()

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        upstream: asyncio.StreamWriter | None = None
        pumps: list[asyncio.Task[None]] = []
        established = False
        try:
            async with asyncio.timeout(10):
                raw = await reader.readuntil(b"\r\n\r\n")
                lines = raw.decode("iso-8859-1").split("\r\n")
                method, target, version = lines[0].split(" ")
                if version not in {"HTTP/1.0", "HTTP/1.1"}:
                    raise ValueError("Bad request")
                headers: dict[str, str] = {}
                for line in lines[1:-2]:
                    name, value = line.split(":", 1)
                    name = name.lower()
                    if not name or any(not (c.isalnum() or c == '-') for c in name) or name in headers:
                        raise ValueError("Ambiguous headers")
                    headers[name] = value.strip()
                expected = "Basic " + base64.b64encode(f"agentra:{self.password}".encode()).decode()
                if not hmac.compare_digest(headers.get("proxy-authorization", ""), expected):
                    writer.write(b'HTTP/1.1 407 Proxy Authentication Required\r\nProxy-Authenticate: Basic realm="Agentra"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                    await writer.drain()
                    return
                parsed = urlsplit("https://" + target if method == "CONNECT" else target)
                if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                    raise ValueError("Invalid destination")
                if method == "CONNECT":
                    if parsed.path or parsed.query or parsed.port != 443:
                        raise ValueError("CONNECT requires HTTPS port")
                    port = 443
                else:
                    if parsed.scheme != "http" or method not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}:
                        raise ValueError("Unsupported proxy request")
                    port = parsed.port or 80
                    if port != 80:
                        raise ValueError("Invalid HTTP port")
                remote_reader, upstream = await self.connect(parsed.hostname, port)
                if method == "CONNECT":
                    writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                    await writer.drain()
                else:
                    path = parsed.path or "/"
                    if parsed.query:
                        path += "?" + parsed.query
                    forbidden = {"proxy-authorization", "proxy-connection", "connection", "host"}
                    forwarded = "".join(f"{k}: {v}\r\n" for k, v in headers.items() if k not in forbidden)
                    upstream.write(f"{method} {path} HTTP/1.1\r\nHost: {parsed.netloc}\r\n{forwarded}Connection: close\r\n\r\n".encode("iso-8859-1"))
                    await upstream.drain()
                established = True
            async with asyncio.timeout(300):
                pumps = [asyncio.create_task(self.pipe(reader, upstream)), asyncio.create_task(self.pipe(remote_reader, writer))]
                done, _ = await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
        except (ValueError, OSError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            if not established:
                with suppress(OSError):
                    writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                    await writer.drain()
        finally:
            for pump in pumps:
                pump.cancel()
            if pumps:
                await asyncio.gather(*pumps, return_exceptions=True)
            for connection in (writer, upstream):
                if connection:
                    connection.close()
                    with suppress(OSError):
                        await connection.wait_closed()

    async def close(self) -> None:
        self.closed = True
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

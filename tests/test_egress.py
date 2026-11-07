import asyncio
import base64
import socket
import pytest
from agentra.egress import EgressProxy
from agentra.security import resolve_public


async def test_mixed_dns_fails_closed(monkeypatch):
    async def records(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443)), (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]
    monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', records)
    with pytest.raises(ValueError):
        await resolve_public('example.test', 443)


@pytest.mark.parametrize('destination', ['127.0.0.1:443', '169.254.169.254:443', '[::1]:443', 'example.com:22'])
async def test_proxy_blocks_private_and_non_web_ports(destination):
    proxy = EgressProxy()
    await proxy.start()
    try:
        port = proxy.server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection('127.0.0.1', port)
        auth = base64.b64encode(f'agentra:{proxy.password}'.encode()).decode()
        writer.write(f'CONNECT {destination} HTTP/1.1\r\nProxy-Authorization: Basic {auth}\r\n\r\n'.encode())
        await writer.drain()
        assert (await reader.read()).startswith(b'HTTP/1.1 403')
        writer.close()
        await writer.wait_closed()
    finally:
        await proxy.close()


async def test_proxy_requires_credentials():
    proxy = EgressProxy()
    await proxy.start()
    try:
        reader, writer = await asyncio.open_connection('127.0.0.1', proxy.server.sockets[0].getsockname()[1])
        writer.write(b'CONNECT example.com:443 HTTP/1.1\r\n\r\n')
        await writer.drain()
        assert (await reader.read()).startswith(b'HTTP/1.1 407')
        writer.close()
        await writer.wait_closed()
    finally:
        await proxy.close()


async def test_connect_uses_validated_numeric_address(monkeypatch):
    import agentra.egress as module
    async def resolve(host, port):
        return ['93.184.216.34']
    called = []
    async def connection(host, port):
        called.append((host, port))
        raise OSError('test ends before network')
    monkeypatch.setattr(module, 'resolve_public', resolve)
    monkeypatch.setattr(asyncio, 'open_connection', connection)
    with pytest.raises(OSError):
        await EgressProxy().connect('attacker.test', 443)
    assert called == [('93.184.216.34', 443)]

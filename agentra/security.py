import asyncio
import hashlib
import hmac
import ipaddress
import json
import os
import socket
from urllib.parse import urlsplit
from fastapi import HTTPException


async def validate_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("URL must use HTTP(S), without embedded credentials")
    host = parsed.hostname.rstrip(".").lower()
    await resolve_public(host, parsed.port or (443 if parsed.scheme == "https" else 80))


async def resolve_public(host: str, port: int) -> list[str]:
    """Resolve once, validate every answer, and return numeric connection targets."""
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("Local destinations are denied")
    if port not in {80, 443}:
        raise ValueError("Only HTTP and HTTPS destination ports are allowed")
    records = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not records:
        raise ValueError("No DNS records")
    addresses: list[str] = []
    for record in records:
        address = ipaddress.ip_address(str(record[4][0]).split("%")[0])
        if not address.is_global or (isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped and not address.ipv4_mapped.is_global):
            raise ValueError("Non-public destinations are denied")
        addresses.append(str(address))
    return list(dict.fromkeys(addresses))


def tenant_for_token(authorization: str) -> str:
    tokens: dict[str, str] = json.loads(os.environ.get("AGENTRA_TOKENS", "{}"))
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Bearer token required")
    supplied = hashlib.sha256(authorization[7:].encode()).digest()
    for tenant, token in tokens.items():
        if len(token) >= 32 and hmac.compare_digest(supplied, hashlib.sha256(token.encode()).digest()):
            return tenant
    raise HTTPException(401, "Invalid token")


def verify_approval(token: str) -> bool:
    secret = os.environ.get("AGENTRA_APPROVER_TOKEN", "")
    return len(secret) >= 32 and hmac.compare_digest(hashlib.sha256(token.encode()).digest(), hashlib.sha256(secret.encode()).digest())

import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit, urlunsplit

from app.core.exceptions import BridgeError


def normalize_url(url: str) -> str:
    try:
        if any(ord(c) < 33 for c in url) or "\\" in url:
            raise ValueError("Invalid characters")
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Expected HTTP(S)")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("Credentials are not permitted")
        host = parsed.hostname.encode("idna").decode().lower().rstrip(".")
        port = parsed.port
        if port not in (None, 80, 443):
            raise ValueError("Only ports 80 and 443 are supported")
        if "%" in host:
            raise ValueError("Scoped hosts are not supported")
        authority = f"[{host}]" if ":" in host else host
        if port and port != (443 if parsed.scheme == "https" else 80):
            authority += f":{port}"
        return urlunsplit((parsed.scheme.lower(), authority, parsed.path or "/", parsed.query, ""))
    except (ValueError, UnicodeError) as exc:
        raise BridgeError(
            "INVALID_URL", "Provide an HTTP(S) URL without credentials on port 80 or 443."
        ) from exc


def safe_link(base: str | None, target: str) -> str | None:
    try:
        return normalize_url(urljoin(base or "", target))
    except BridgeError:
        return None


def public_ip(value: str) -> bool:
    address = ipaddress.ip_address(value)
    if str(address) == "168.63.129.16":  # Azure platform virtual IP, despite global addressing.
        return False
    return address.is_global and not (
        address.is_multicast
        or address.is_reserved
        or getattr(address, "ipv4_mapped", None)
        or getattr(address, "sixtofour", None)
        or getattr(address, "teredo", None)
    )


class URLPolicy:
    async def resolve(self, url: str) -> tuple[str, str]:
        normalized = normalize_url(url)
        parsed = urlsplit(normalized)
        host = parsed.hostname
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            raise BridgeError("BLOCKED_URL", "Local network targets are blocked.", 403)
        try:
            addresses = [str(ipaddress.ip_address(host))]
        except ValueError:
            try:
                records = await asyncio.wait_for(
                    asyncio.get_running_loop().getaddrinfo(
                        host,
                        parsed.port or (443 if parsed.scheme == "https" else 80),
                        type=socket.SOCK_STREAM,
                    ),
                    timeout=5,
                )
                addresses = sorted({record[4][0] for record in records})
            except (OSError, TimeoutError) as exc:
                raise BridgeError("FETCH_FAILED", "The target hostname could not be resolved.", 502) from exc
        if not addresses or not all(public_ip(address) for address in addresses):
            raise BridgeError("BLOCKED_URL", "Non-public network targets are blocked.", 403)
        return normalized, addresses[0]

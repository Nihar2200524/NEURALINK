"""Explicit public-network smoke check: python -m scripts.network_smoke."""
import asyncio
from agentra.session_manager import SessionManager
from agentra.config import BrowserSettings
from agentra.action_dispatcher import dispatch
from agentra.models import Action


async def main() -> None:
    manager = SessionManager(BrowserSettings())
    await manager.start()
    try:
        session = await manager.create("network-smoke")
        receipt = await dispatch(session, Action(kind="NAVIGATE", url="https://example.com", timeout_ms=30000), approved=True)
        print(receipt.status, receipt.detail)
        if receipt.status != "VERIFIED":
            raise RuntimeError("Public HTTPS proxy smoke test failed")
        print("Public page loaded through the DNS-pinning proxy.")
    finally:
        await manager.close()


if __name__ == "__main__":
    asyncio.run(main())

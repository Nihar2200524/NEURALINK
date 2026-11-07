"""Task-scoped readiness; no network-idle or global quiescence requirement."""
import asyncio
from typing import Literal
from playwright.async_api import Error, TimeoutError as PlaywrightTimeout, expect
from .session_manager import Session
from .state_engine import resolve


async def readiness(session: Session, ref: str, timeout_ms: int) -> Literal["READY", "PARTIAL", "TIMEOUT"]:
    locator = await resolve(session, ref)
    attached = False
    try:
        async with asyncio.timeout(timeout_ms / 1000):
            await locator.wait_for(state="attached", timeout=timeout_ms)
            attached = True
            await expect(locator).to_be_visible(timeout=timeout_ms)
            tag = await locator.evaluate("e => e.tagName.toLowerCase()")
            if tag in {"input", "textarea"}:
                input_type = await locator.get_attribute("type")
                if input_type not in {"checkbox", "radio", "button", "submit", "reset", "file"}:
                    await expect(locator).to_be_editable(timeout=timeout_ms)
                else:
                    await locator.click(trial=True, timeout=timeout_ms)
            elif tag in {"button", "a", "select"}:
                await locator.click(trial=True, timeout=timeout_ms)
            return "READY"
    except (TimeoutError, PlaywrightTimeout, AssertionError):
        return "PARTIAL" if attached else "TIMEOUT"
    except Error:
        return "TIMEOUT"

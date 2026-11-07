import asyncio
import time
import uuid
from playwright.async_api import Error, TimeoutError as PlaywrightTimeout, expect
from .models import Action, Receipt, State
from .security import validate_url
from .session_manager import Session
from .state_engine import capture, resolve


async def dispatch(session: Session, action: Action, approved: bool = False, action_id: str | None = None) -> Receipt:
    aid = action_id or uuid.uuid4().hex
    try:
        locator = None
        if action.scoped_ref:
            locator = await resolve(session, action.scoped_ref)
        if action.kind == "NAVIGATE":
            await validate_url(action.url or "")
        if not approved:
            if len(session.pending) >= 100:
                raise ValueError("Too many pending approvals")
            session.pending[aid] = (action.model_copy(deep=True), time.monotonic() + 300)
            return Receipt(status="AUTHORIZATION_REQUIRED", action_id=aid, detail="All mutations require separate approver credentials; approval expires in 300 seconds")
        async with asyncio.timeout(action.timeout_ms / 1000):
            page = session.pages[action.tab_id]
            if locator is not None:
                scope = "::".join((action.scoped_ref or "").split("::")[1:3])
                frame = (await session.topology())[scope]
                page = frame.page
            else:
                frame = page.main_frame
            if action.kind == "NAVIGATE":
                await page.goto(action.url or "", wait_until="domcontentloaded")
                await validate_url(page.url)
                if page.url == "about:blank":
                    raise ValueError("Navigation did not resolve")
            elif locator is not None:
                if action.kind == "CLICK":
                    await locator.click()
                elif action.kind == "TYPE":
                    await locator.fill(action.text)
                    await expect(locator).to_have_value(action.text)
                    if action.press_enter:
                        await locator.press("Enter")
                elif action.kind == "SELECT_OPTION":
                    await locator.select_option(action.value)
                    await expect(locator).to_have_value(action.value)
                elif action.kind == "CHECK":
                    await locator.check()
                    await expect(locator).to_be_checked()
            post = action.postcondition
            if post:
                target = frame.locator(post.selector) if post.selector else locator
                if post.kind == "url":
                    await expect(page).to_have_url(post.value)
                elif target is None:
                    raise ValueError("Postcondition requires selector")
                elif post.kind == "visible":
                    await expect(target).to_be_visible()
                elif post.kind == "hidden":
                    await expect(target).to_be_hidden()
                elif post.kind == "text":
                    await expect(target).to_have_text(post.value)
                elif post.kind == "expanded":
                    await expect(target).to_have_attribute("aria-expanded", post.value)
        return Receipt(status="VERIFIED", action_id=aid, detail="Observable postcondition satisfied", state=await capture(session))
    except ValueError as exc:
        stale = str(exc) == "STALE_REFERENCE_ERROR"
        return Receipt(status="STALE_REFERENCE_ERROR" if stale else "FAILED", action_id=aid, detail="Reference is stale" if stale else "Validation failed", state=await safe_capture(session))
    except (TimeoutError, PlaywrightTimeout, AssertionError):
        return Receipt(status="TIMEOUT", action_id=aid, detail="Postcondition or actionability deadline unmet; effect may have occurred, do not blindly retry", state=await safe_capture(session))
    except (Error, KeyError, OSError):
        return Receipt(status="FAILED", action_id=aid, detail="Browser operation failed; effect may have occurred", state=await safe_capture(session))


async def safe_capture(session: Session) -> State | None:
    try:
        return await capture(session)
    except (Error, ValueError):
        return None

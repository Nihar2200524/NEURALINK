import asyncio
import time
import uuid
from playwright.async_api import Error, TimeoutError as PlaywrightTimeout, expect
from .models import Action, Receipt, State
from .security import validate_url
from .session_manager import Session
from .state_engine import capture, resolve
from .telemetry import OUTCOMES, LATENCY, audit


async def dispatch(session: Session, action: Action, approved: bool = False, action_id: str | None = None) -> Receipt:
    aid = action_id or uuid.uuid4().hex
    started = time.monotonic()
    try:
        async with asyncio.timeout(action.timeout_ms / 1000):
            receipt = await execute(session, action, approved, aid)
    except TimeoutError:
        receipt = Receipt(status="TIMEOUT", action_id=aid, detail="Action deadline exceeded; effect may have occurred; do not automatically retry", state=await safe_capture(session))
    LATENCY.observe(time.monotonic() - started)
    OUTCOMES.labels(action.kind, receipt.status).inc()
    audit("action_receipt", session.id, receipt.status)
    return receipt


async def execute(session: Session, action: Action, approved: bool = False, action_id: str | None = None) -> Receipt:
    aid = action_id or uuid.uuid4().hex
    try:
        locator = None
        if action.scoped_ref:
            locator = await resolve(session, action.scoped_ref)
        if action.kind == "NAVIGATE":
            await validate_url(action.url or "")
        if not approved:
            for expired, (_, deadline) in list(session.pending.items()):
                if deadline < time.monotonic():
                    session.pending.pop(expired, None)
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
            post = action.postcondition
            if post and (action.kind == "CLICK" or action.press_enter):
                target = frame.locator(post.selector) if post.selector else locator
                already = page.url == post.value if post.kind == "url" else False
                if target is not None and post.kind != "url":
                    if post.kind == "visible":
                        already = await target.is_visible()
                    elif post.kind == "hidden":
                        already = not await target.is_visible()
                    elif await target.count() == 1:
                        if post.kind == "text":
                            already = await target.inner_text() == post.value
                        elif post.kind == "expanded":
                            already = await target.get_attribute("aria-expanded") == post.value
                if already:
                    return Receipt(status="FAILED", action_id=aid, detail="POSTCONDITION_ALREADY_SATISFIED: choose evidence that changes after the action", state=await safe_capture(session))
            if action.kind == "NAVIGATE":
                await page.goto(action.url or "", wait_until="domcontentloaded")
                await validate_url(page.url)
                if page.url == "about:blank":
                    raise ValueError("Navigation did not resolve")
            elif locator is not None:
                if action.kind == "CLICK":
                    await locator.click(trial=True)
                    await resolve(session, action.scoped_ref or "")
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
        return Receipt(status="VERIFIED", action_id=aid, detail="Observable postcondition satisfied", state=await safe_capture(session))
    except ValueError as exc:
        stale = str(exc) == "STALE_REFERENCE_ERROR"
        return Receipt(status="STALE_REFERENCE_ERROR" if stale else "FAILED", action_id=aid, detail="Reference is stale" if stale else "Validation failed", state=await safe_capture(session))
    except (TimeoutError, PlaywrightTimeout, AssertionError):
        return Receipt(status="TIMEOUT", action_id=aid, detail="Postcondition or actionability deadline unmet; effect may have occurred, do not blindly retry", state=await safe_capture(session))
    except (Error, KeyError, OSError):
        return Receipt(status="FAILED", action_id=aid, detail="Browser operation failed; effect may have occurred", state=await safe_capture(session))


async def safe_capture(session: Session) -> State | None:
    try:
        async with asyncio.timeout(2):
            return await capture(session)
    except (Error, ValueError, TimeoutError):
        return None

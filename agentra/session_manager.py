import asyncio
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from contextlib import asynccontextmanager, suppress
from collections.abc import AsyncIterator
from typing import Literal
from playwright.async_api import Browser, BrowserContext, Error, Frame, Locator, Page, Playwright, Route, async_playwright
from .models import Action, Receipt
from .security import validate_url
from .config import BrowserSettings

# The observer is a freshness aid, not a security boundary against hostile JS.
OBSERVER = """(documentId) => {
 if (!window.__agentraEpoch) {
   window.__agentraEpoch = {id: documentId, revision: 0};
   new MutationObserver(() => window.__agentraEpoch.revision++).observe(document,
     {subtree:true, childList:true, attributes:true, characterData:true});
 }
 return JSON.stringify(window.__agentraEpoch);
}"""


@dataclass
class Session:
    tenant: str
    context: BrowserContext
    directory: tempfile.TemporaryDirectory[str]
    browser: Browser
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pages: dict[str, Page] = field(default_factory=dict)
    frames: dict[str, Frame] = field(default_factory=dict)
    refs: dict[str, Locator] = field(default_factory=dict)
    epochs: dict[str, str] = field(default_factory=dict)
    pending: dict[str, tuple[Action, float]] = field(default_factory=dict)
    results: dict[str, tuple[str, Receipt]] = field(default_factory=dict)
    version: int = 0
    touched: float = field(default_factory=time.monotonic)
    lifecycle: Literal["ACTIVE", "CRASHED", "CLOSED"] = "ACTIVE"
    generation: int = 1
    failure: str | None = None

    def mark_crashed(self, browser: Browser, reason: str) -> None:
        if self.lifecycle == "ACTIVE" and self.browser is browser:
            self.lifecycle = "CRASHED"
            self.failure = reason
            self.invalidate_pending()

    def invalidate_pending(self) -> None:
        pending_ids = set(self.pending)
        self.pending.clear()
        self.refs.clear()
        self.epochs.clear()
        for key, (fingerprint, receipt) in self.results.items():
            if receipt.action_id in pending_ids:
                self.results[key] = (fingerprint, Receipt(status="FAILED", action_id=receipt.action_id, detail="Session worker invalidated; authorization cancelled"))

    @asynccontextmanager
    async def operation(self) -> AsyncIterator[None]:
        async with self.lock:
            if self.lifecycle != "ACTIVE":
                raise SessionUnavailable(self.lifecycle)
            self.touched = time.monotonic()
            try:
                yield
            finally:
                self.touched = time.monotonic()

    def register(self, page: Page) -> None:
        if page not in self.pages.values():
            self.pages[f"tab_{len(self.pages)}"] = page
            browser = self.browser
            page.on("crash", lambda page: self.mark_crashed(browser, "PAGE_CRASHED"))

    async def topology(self) -> dict[str, Frame]:
        result: dict[str, Frame] = {}
        for tab, page in self.pages.items():
            if not page.is_closed():
                for frame in page.frames:
                    if frame not in self.frames.values():
                        self.frames[f"frame_{len(self.frames)}"] = frame
                    fid = next(key for key, value in self.frames.items() if value == frame)
                    result[f"{tab}::{fid}"] = frame
        return result

    async def fingerprints(self) -> dict[str, str]:
        result = {}
        for key, frame in (await self.topology()).items():
            result[key] = frame.url + str(await frame.evaluate(OBSERVER, uuid.uuid4().hex))
        return result


class SessionUnavailable(Exception):
    pass


class SessionManager:
    def __init__(self, settings: BrowserSettings | None = None) -> None:
        self.settings = settings or BrowserSettings.from_env()
        self.sessions: dict[str, Session] = {}
        self.playwright: Playwright | None = None
        self.capacity_lock = asyncio.Lock()
        self.closing = False

    async def start(self) -> None:
        self.playwright = await async_playwright().start()

    async def launch_worker(self, directory: str) -> tuple[Browser, BrowserContext]:
        if not self.playwright or self.closing:
            raise ValueError("Browser service unavailable")
        browser = await self.playwright.chromium.launch(
            chromium_sandbox=True, downloads_path=directory,
            headless=not self.settings.headed, slow_mo=self.settings.slow_mo_ms,
        )
        try:
            context = await browser.new_context(accept_downloads=False, service_workers="block")
            context.set_default_timeout(10000)
            async def guard(route: Route) -> None:
                try:
                    async with asyncio.timeout(5):
                        await validate_url(route.request.url)
                except (ValueError, OSError, TimeoutError):
                    await route.abort("blockedbyclient")
                else:
                    await route.continue_()
            await context.route("**/*", guard)
            await context.route_web_socket("**/*", lambda ws: ws.close())
            return browser, context
        except BaseException:
            await browser.close()
            raise

    def bind_worker(self, session: Session) -> None:
        browser = session.browser
        browser.on("disconnected", lambda disconnected: session.mark_crashed(browser, "BROWSER_DISCONNECTED"))
        session.context.on("page", session.register)

    async def create(self, tenant: str) -> Session:
        async with self.capacity_lock:
            if len(self.sessions) >= 20:
                raise ValueError("Session capacity reached")
            directory = tempfile.TemporaryDirectory(prefix="agentra-")
            browser = None
            try:
                browser, context = await self.launch_worker(directory.name)
                session = Session(tenant, context, directory, browser)
                self.bind_worker(session)
                session.register(await context.new_page())
                self.sessions[session.id] = session
                return session
            except BaseException:
                if browser:
                    await browser.close()
                directory.cleanup()
                raise

    async def recover(self, session: Session) -> None:
        async with session.lock:
            if session.lifecycle == "CLOSED" or self.closing:
                raise SessionUnavailable("CLOSED")
            if session.lifecycle == "ACTIVE":
                return
            # Never reload URLs, restore credentials, or replay uncertain effects.
            session.invalidate_pending()
            await self.stop_worker(session)
            browser, context = await self.launch_worker(session.directory.name)
            session.browser, session.context = browser, context
            session.pages.clear()
            session.frames.clear()
            session.version += 1
            session.generation += 1
            session.failure = None
            session.lifecycle = "ACTIVE"
            self.bind_worker(session)
            try:
                session.register(await context.new_page())
            except BaseException:
                session.mark_crashed(browser, "RECOVERY_FAILED")
                await self.stop_worker(session)
                raise
            session.touched = time.monotonic()

    async def stop_worker(self, session: Session) -> None:
        try:
            with suppress(Error):
                await session.context.close()
        finally:
            with suppress(Error):
                await session.browser.close()

    async def delete(self, session: Session, idle_seconds: float | None = None) -> None:
        async with session.lock:
            if session.lifecycle == "CLOSED":
                return
            if idle_seconds is not None and time.monotonic() - session.touched <= idle_seconds:
                return
            session.lifecycle = "CLOSED"
            session.invalidate_pending()
            self.sessions.pop(session.id, None)
            try:
                await self.stop_worker(session)
            finally:
                session.directory.cleanup()

    async def reap(self) -> None:
        while True:
            await asyncio.sleep(30)
            for session in list(self.sessions.values()):
                if not session.lock.locked() and time.monotonic() - session.touched > 900:
                    await self.delete(session, idle_seconds=900)

    async def close(self) -> None:
        async with self.capacity_lock:
            self.closing = True
            for session in list(self.sessions.values()):
                await self.delete(session)
        if self.playwright:
            await self.playwright.stop()

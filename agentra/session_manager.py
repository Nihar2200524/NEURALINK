import asyncio
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from contextlib import asynccontextmanager, suppress
from collections.abc import AsyncIterator
from typing import Literal
import psutil  # type: ignore[import-untyped]
from playwright.async_api import Browser, BrowserContext, Error, Frame, Locator, Page, Playwright, Route, async_playwright
from .models import Action, Receipt
from .security import validate_url
from .config import BrowserSettings
from .egress import EgressProxy
from .telemetry import SESSIONS, RECOVERIES, LIMITS, audit

# The observer is a freshness aid, not a security boundary against hostile JS.
OBSERVER = """(documentId) => {
 if (!window.__agentraEpoch) {
   window.__agentraEpoch = {id: documentId, revision: 0};
   new MutationObserver(() => window.__agentraEpoch.revision++).observe(document,
     {subtree:true, childList:true, attributes:true, characterData:true});
 }
 let hash=2166136261, scanned=0;
 const add=s=>{for(let i=0;i<s.length;i++){hash^=s.charCodeAt(i);hash=Math.imul(hash,16777619);}};
 const visit=root=>{
   for(const element of root.querySelectorAll('*')){
     if(++scanned>20000)throw Error('FRESHNESS_SCAN_LIMIT');
     if(element.matches('input,textarea,select'))add(element.value+'|'+element.checked);
     if(element.shadowRoot){add(element.shadowRoot.innerHTML);visit(element.shadowRoot);}
   }
 };
 visit(document);
 return JSON.stringify([window.__agentraEpoch, hash]);
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
    worker_pid: int = 0
    worker_created: float = 0
    max_tabs: int = 12
    monitor: asyncio.Task[None] | None = None
    background: set[asyncio.Task[None]] = field(default_factory=set)
    waiting: int = 0

    def mark_crashed(self, browser: Browser, reason: str) -> None:
        if self.lifecycle == "ACTIVE" and self.browser is browser:
            self.lifecycle = "CRASHED"
            self.failure = reason
            self.invalidate_pending()
            audit("worker_failed", self.id, reason)

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
        if self.waiting >= 32:
            raise SessionUnavailable("QUEUE_FULL")
        self.waiting += 1
        try:
            async with asyncio.timeout(30):
                await self.lock.acquire()
        finally:
            self.waiting -= 1
        try:
            if self.lifecycle != "ACTIVE":
                raise SessionUnavailable(self.lifecycle)
            self.touched = time.monotonic()
            try:
                yield
            finally:
                self.touched = time.monotonic()
        finally:
            self.lock.release()

    def register(self, page: Page) -> None:
        if page in self.pages.values():
            return
        if sum(not item.is_closed() for item in self.pages.values()) >= self.max_tabs:
            task = asyncio.create_task(page.close())
            self.background.add(task)
            task.add_done_callback(self.background.discard)
            return
        if page not in self.pages.values():
            self.pages[f"tab_{len(self.pages)}"] = page
            browser = self.browser
            page.on("crash", lambda page: self.mark_crashed(browser, "PAGE_CRASHED"))

    async def topology(self) -> dict[str, Frame]:
        result: dict[str, Frame] = {}
        for tab, page in list(self.pages.items()):
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
        self.proxy = EgressProxy()

    async def start(self) -> None:
        await self.proxy.start()
        try:
            self.playwright = await async_playwright().start()
        except BaseException:
            await self.proxy.close()
            raise

    async def launch_worker(self, directory: str) -> tuple[Browser, BrowserContext]:
        if not self.playwright or self.closing:
            raise ValueError("Browser service unavailable")
        browser = await self.playwright.chromium.launch(
            chromium_sandbox=True, downloads_path=directory,
            headless=not self.settings.headed, slow_mo=self.settings.slow_mo_ms,
            proxy={"server": self.proxy.address, "username": "agentra", "password": self.proxy.password},
            args=["--proxy-bypass-list=<-loopback>", "--disable-quic", "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"],
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

    async def track_worker(self, session: Session) -> None:
        cdp = await session.browser.new_browser_cdp_session()
        try:
            info = await cdp.send("SystemInfo.getProcessInfo")
            session.worker_pid = int(next(p["id"] for p in info["processInfo"] if p["type"] == "browser"))
            session.worker_created = float(psutil.Process(session.worker_pid).create_time())
        finally:
            await cdp.detach()
        session.monitor = asyncio.create_task(self.monitor_worker(session, session.browser))

    def memory_bytes(self, session: Session) -> int:
        process = psutil.Process(session.worker_pid)
        if process.create_time() != session.worker_created:
            raise ProcessLookupError("Worker identity changed")
        total = 0
        for child in [process, *process.children(recursive=True)]:
            with suppress(psutil.NoSuchProcess):
                total += int(child.memory_info().rss)
        return total

    async def monitor_worker(self, session: Session, browser: Browser) -> None:
        while session.browser is browser and session.lifecycle == "ACTIVE":
            await asyncio.sleep(1)
            try:
                if self.memory_bytes(session) <= self.settings.session_memory_mb * 1024 * 1024:
                    continue
                reason = "MEMORY_LIMIT"
            except (psutil.Error, ProcessLookupError):
                reason = "RESOURCE_MONITOR_FAILED"
            session.mark_crashed(browser, reason)
            LIMITS.inc()
            with suppress(Error):
                await browser.close()
            return

    async def create(self, tenant: str) -> Session:
        async with self.capacity_lock:
            if len(self.sessions) >= self.settings.max_sessions:
                raise ValueError("Session capacity reached")
            directory = tempfile.TemporaryDirectory(prefix="agentra-")
            browser = None
            try:
                browser, context = await self.launch_worker(directory.name)
                session = Session(tenant, context, directory, browser)
                session.max_tabs = self.settings.max_tabs
                self.bind_worker(session)
                session.register(await context.new_page())
                await self.track_worker(session)
                self.sessions[session.id] = session
                SESSIONS.inc()
                audit("session_created", session.id, "ACTIVE")
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
                await self.track_worker(session)
            except BaseException:
                session.mark_crashed(browser, "RECOVERY_FAILED")
                await self.stop_worker(session)
                raise
            session.touched = time.monotonic()
            RECOVERIES.inc()
            audit("session_recovered", session.id, "ACTIVE")

    async def stop_worker(self, session: Session) -> None:
        if session.monitor and session.monitor is not asyncio.current_task():
            session.monitor.cancel()
            await asyncio.gather(session.monitor, return_exceptions=True)
        for task in list(session.background):
            task.cancel()
        await asyncio.gather(*session.background, return_exceptions=True)
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
            SESSIONS.dec()
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
        await self.proxy.close()

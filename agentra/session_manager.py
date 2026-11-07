import asyncio
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from playwright.async_api import Browser, BrowserContext, Frame, Locator, Page, Playwright, Route, async_playwright
from .models import Action, Receipt
from .security import validate_url

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

    def register(self, page: Page) -> None:
        if page not in self.pages.values():
            self.pages[f"tab_{len(self.pages)}"] = page

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


class SessionManager:
    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.capacity_lock = asyncio.Lock()

    async def start(self) -> None:
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(chromium_sandbox=True)

    async def create(self, tenant: str) -> Session:
        async with self.capacity_lock:
            if len(self.sessions) >= 20:
                raise ValueError("Session capacity reached")
            if not self.browser or not self.browser.is_connected():
                raise ValueError("Browser unavailable; restart service")
            context = await self.browser.new_context(accept_downloads=False, service_workers="block")
            context.set_default_timeout(10000)
            async def guard(route: Route) -> None:
                try:
                    await validate_url(route.request.url)
                except (ValueError, OSError):
                    await route.abort("blockedbyclient")
                else:
                    await route.continue_()
            await context.route("**/*", guard)
            # WebSockets are disabled until an egress-enforcing proxy is configured.
            await context.route_web_socket("**/*", lambda ws: ws.close())
            session = Session(tenant, context, tempfile.TemporaryDirectory(prefix="agentra-"))
            context.on("page", session.register)
            session.register(await context.new_page())
            self.sessions[session.id] = session
            return session

    async def delete(self, session: Session) -> None:
        async with session.lock:
            self.sessions.pop(session.id, None)
            await session.context.close()
            session.directory.cleanup()

    async def reap(self) -> None:
        while True:
            await asyncio.sleep(30)
            for session in list(self.sessions.values()):
                if not session.lock.locked() and time.monotonic() - session.touched > 900:
                    await self.delete(session)

    async def close(self) -> None:
        for session in list(self.sessions.values()):
            await self.delete(session)
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

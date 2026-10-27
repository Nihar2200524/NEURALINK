import asyncio

from app.core.config import Settings
from app.core.exceptions import BridgeError
from app.services.fetcher import FetchedDocument, HTTPFetcher


class BrowserFetcher:
    """Opt-in, stateless rendering. All allowed GETs pass through the pinned HTTP gateway."""

    def __init__(self, settings: Settings, gateway: HTTPFetcher):
        self.settings, self.gateway = settings, gateway
        self.slots = asyncio.Semaphore(1)

    async def fetch(self, url: str) -> FetchedDocument:
        try:
            from playwright.async_api import Error as PlaywrightError
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise BridgeError(
                "BROWSER_UNAVAILABLE", "Install the browser extra and Chromium first.", 503
            ) from exc
        url, _ = await self.gateway.policy.resolve(url)
        if self.gateway.before_request:
            await self.gateway.before_request(url)
        try:
            async with asyncio.timeout(self.settings.timeout * 2), self.slots:
                initial = await self.gateway.fetch(url)
                url = initial.url
                async with async_playwright() as playwright:
                    browser = await playwright.chromium.launch(
                        headless=True,
                        chromium_sandbox=True,
                        # Any network channel missed by interception must fail closed.
                        proxy={"server": "http://127.0.0.1:9"},
                        args=[
                            "--disable-background-networking",
                            "--proxy-bypass-list=<-loopback>",
                            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                        ],
                    )
                    try:
                        context = await browser.new_context(
                            service_workers="block",
                            accept_downloads=False,
                            user_agent=self.settings.user_agent,
                        )
                        await context.route_web_socket("**/*", lambda socket: socket.close())
                        total, count, main_error = 0, 0, None
                        initial_pending = True

                        async def route_request(route):
                            nonlocal total, count, main_error, initial_pending
                            request = route.request
                            count += 1
                            if (
                                request.method != "GET"
                                or request.resource_type
                                not in {"document", "script", "stylesheet", "xhr", "fetch"}
                                or count > 40
                            ):
                                await route.abort()
                                return
                            try:
                                allowed_types = {
                                    "text/html",
                                    "application/xhtml+xml",
                                    "text/plain",
                                    "text/css",
                                    "application/javascript",
                                    "text/javascript",
                                    "application/json",
                                }
                                if initial_pending and request.url == initial.url:
                                    initial_pending = False
                                    document = initial
                                else:
                                    document = await self.gateway.retrieve(request.url, allowed_types)
                                total += len(document.html.encode())
                                if total > self.settings.max_response_bytes * 3:
                                    raise BridgeError(
                                        "CONTENT_TOO_LARGE", "Browser resource budget exceeded.", 413
                                    )
                                # Do not relocate a redirected document under the wrong origin.
                                if document.url != request.url and request.is_navigation_request():
                                    await route.fulfill(
                                        status=302, headers={"location": document.url}, body=""
                                    )
                                else:
                                    await route.fulfill(
                                        status=document.status,
                                        content_type=document.content_type,
                                        body=document.html,
                                    )
                            except BridgeError as exc:
                                if request.is_navigation_request():
                                    main_error = exc
                                await route.abort()

                        await context.route("**/*", route_request)
                        page = await context.new_page()
                        try:
                            await page.goto(
                                url, wait_until="networkidle", timeout=self.settings.timeout * 1000
                            )
                        except PlaywrightError:
                            if main_error:
                                raise main_error
                            raise
                        html = await page.content()
                        if len(html.encode()) > self.settings.max_response_bytes:
                            raise BridgeError(
                                "CONTENT_TOO_LARGE", "Rendered HTML exceeds the size limit.", 413
                            )
                        return FetchedDocument(page.url, html, total, method="browser", cacheable=False)
                    finally:
                        await browser.close()
        except TimeoutError as exc:
            raise BridgeError("FETCH_TIMEOUT", "Browser rendering timed out.", 504) from exc
        except PlaywrightError as exc:
            raise BridgeError(
                "FETCH_FAILED",
                "Browser rendering failed; check Chromium installation and sandbox support.",
                502,
            ) from exc
        except OSError as exc:
            raise BridgeError(
                "BROWSER_UNAVAILABLE", "Browser process could not be started in this environment.", 503
            ) from exc

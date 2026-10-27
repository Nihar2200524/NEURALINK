import asyncio
import hashlib
import json
import time
from html import escape

from lxml.etree import ParserError, XMLSyntaxError

from app.core.config import Settings
from app.core.exceptions import BridgeError
from app.models.request import ExtractRequest, FetchRequest
from app.models.response import BridgeResponse, ContentBlock
from app.services.cache import Cache, MemoryCache
from app.services.cleaner import ContentCleaner
from app.services.extractor import ContentExtractor
from app.services.fetcher import FetchedDocument, HTTPFetcher
from app.services.formatter import Formatter
from app.services.parser import HTMLParser, ParsedPage
from app.services.robots import RobotsPolicy
from app.utils.urls import normalize_url


class RequestManager:
    def __init__(self, settings: Settings, fetcher: HTTPFetcher | None = None, cache: Cache | None = None):
        self.settings = settings
        self.fetcher = fetcher or HTTPFetcher(settings)
        self.cache = cache or MemoryCache(settings.cache_ttl, settings.cache_entries)
        # Robots has a separate transport so checking policy cannot deadlock occupied fetch slots.
        self.robots_fetcher = HTTPFetcher(settings)
        self.robots = RobotsPolicy(self.robots_fetcher, settings.user_agent)
        if settings.respect_robots:
            self.fetcher.before_request = self.robots.check
        self.browser = None
        self.processing_slots = asyncio.Semaphore(settings.concurrency)

    async def close(self) -> None:
        await self.fetcher.close()
        await self.robots_fetcher.close()

    @staticmethod
    def key(prefix: str, value) -> str:
        return prefix + hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    async def fetch(self, options: FetchRequest) -> BridgeResponse:
        options = options.model_copy(update={"url": normalize_url(options.url)})
        key = self.key("response:", options.model_dump())
        cached = await self.cache.get(key)
        if cached is not None:
            if cached.metadata is not None:
                cached.metadata["cached"] = True
                cached.metadata["fetch_duration_ms"] = 0
                cached.metadata["parse_duration_ms"] = 0
            return cached
        doc_key = self.key("document:", [options.url, options.render])
        document = await self.cache.get(doc_key)
        fetched_cached = document is not None
        started = time.perf_counter()
        if document is None:
            if options.render == "browser":
                document = await self.browser_fetch(options.url)
            else:
                document = await self.fetcher.fetch(options.url)
            if document.cacheable:
                await self.cache.set(doc_key, document)
        fetch_ms = round((time.perf_counter() - started) * 1000, 2)
        parsed, blocks, parse_ms = await self.process(document)
        if (
            options.render == "auto"
            and self.settings.browser_enabled
            and sum(len(b.text) for b in blocks) < 160
        ):
            document = await self.browser_fetch(options.url)
            parsed, blocks, parse_ms = await self.process(document)
        if not blocks:
            raise BridgeError("NO_CONTENT", "No meaningful content was found.", 422)
        response = Formatter().format(
            parsed,
            blocks,
            options,
            options.url,
            document.raw_bytes,
            {
                "content_type": document.content_type,
                "fetch_method": document.method,
                "cached": fetched_cached,
                "final_url": document.url,
                "fetch_duration_ms": fetch_ms,
                "parse_duration_ms": parse_ms,
            },
        )
        if document.cacheable:
            await self.cache.set(key, response)
        return response

    async def browser_fetch(self, url: str) -> FetchedDocument:
        if not self.settings.browser_enabled:
            raise BridgeError("BROWSER_DISABLED", "Browser rendering is not enabled.", 400)
        if self.browser is None:
            from app.services.browser import BrowserFetcher

            self.browser = BrowserFetcher(self.settings, self.fetcher)
        return await self.browser.fetch(url)

    async def extract(self, options: ExtractRequest) -> BridgeResponse:
        url = normalize_url(options.url) if options.url else None
        document = FetchedDocument(url or "", options.html, len(options.html.encode()), method="submitted")
        parsed, blocks, parse_ms = await self.process(document)
        if not blocks:
            raise BridgeError("NO_CONTENT", "No meaningful content was found.", 422)
        return Formatter().format(
            parsed,
            blocks,
            options,
            url,
            document.raw_bytes,
            {
                "content_type": "text/html",
                "fetch_method": "submitted",
                "cached": False,
                "parse_duration_ms": parse_ms,
            },
        )

    async def process(self, document: FetchedDocument) -> tuple[ParsedPage, list[ContentBlock], float]:
        key = self.key("parsed:", [document.url, document.html, document.content_type])
        cached = await self.cache.get(key) if document.cacheable else None
        if cached is not None:
            return *cached, 0
        started = time.perf_counter()
        async with self.processing_slots:
            try:
                parsed, blocks = await asyncio.to_thread(self._process, document)
            except (ParserError, XMLSyntaxError, RecursionError) as exc:
                raise BridgeError("PARSE_FAILED", "The document could not be parsed safely.", 422) from exc
        if document.cacheable:
            await self.cache.set(key, (parsed, blocks))
        return parsed, blocks, round((time.perf_counter() - started) * 1000, 2)

    @staticmethod
    def _process(document: FetchedDocument) -> tuple[ParsedPage, list[ContentBlock]]:
        html = (
            "<pre>" + escape(document.html) + "</pre>"
            if document.content_type == "text/plain"
            else document.html
        )
        parsed = HTMLParser().parse(html, document.url or None)
        soup = ContentCleaner().clean(parsed.soup)
        blocks = ContentExtractor().extract(soup, document.url or None)
        soup.decompose()
        parsed.soup = None  # Cache compact data, not the large mutable DOM.
        return parsed, blocks

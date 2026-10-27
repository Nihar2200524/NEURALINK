import json
from dataclasses import dataclass

from bs4 import BeautifulSoup

from app.models.response import Page
from app.utils.text import compact
from app.utils.urls import safe_link


@dataclass
class ParsedPage:
    soup: BeautifulSoup | None
    page: Page
    raw_text: str
    metadata: dict


class HTMLParser:
    def parse(self, html: str, url: str | None = None) -> ParsedPage:
        soup = BeautifulSoup(html, "lxml")

        def meta(key: str) -> str:
            node = soup.find("meta", attrs={"name": key}) or soup.find("meta", attrs={"property": key})
            return compact(str(node.get("content", "")))[:2000] if node else ""

        canonical = soup.find("link", rel="canonical")
        title = compact(soup.title.get_text()) if soup.title else meta("og:title")
        page = Page(
            title=title[:500],
            description=meta("description") or meta("og:description"),
            canonical_url=safe_link(url, str(canonical.get("href", ""))) if canonical else url,
            language=str(soup.html.get("lang", ""))[:50] if soup.html else None,
        )
        structured = []
        for script in soup.find_all("script", type="application/ld+json", limit=5):
            if len(script.get_text()) > 20000:
                continue
            try:
                structured.append(json.loads(script.get_text()))
            except (ValueError, RecursionError):
                continue
        metadata = {
            "published_time": meta("article:published_time"),
            "author": meta("author"),
            "structured_data": structured,
        }
        return ParsedPage(soup, page, compact(soup.get_text(" ", strip=True)), metadata)

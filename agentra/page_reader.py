"""Fresh read-only observations independent of action snapshot references."""
import asyncio
from datetime import datetime, timezone
from typing import Any
from playwright.async_api import Page, Error
from .content import EXTRACT

READ = """() => {
 const extract = """ + EXTRACT + """;
 return {url:location.href,title:document.title,content:document.body?extract(document.body):'',
 links:Array.from(document.querySelectorAll('a[href]')).slice(0,250).map(a=>({text:(a.innerText||'').trim().slice(0,300),url:a.href})).filter(a=>/^https?:/.test(a.url)&&a.text)};
}"""


def classify(url: str, title: str, content: str) -> str:
    text = (title + '\n' + content[:12000]).lower()
    if '/sorry/' in url or any(s in text for s in ('our systems have detected unusual traffic', 'verify you are human', 'checking your browser', 'complete the captcha', 'unusual traffic from your computer')):
        return 'HUMAN_REQUIRED'
    if any(s in title.lower() for s in ('access denied', '403 forbidden', 'just a moment')):
        return 'BLOCKED'
    return 'CONTENT_AVAILABLE' if len(content.strip()) >= 40 else 'EMPTY'


async def read_page(page: Page, timeout_ms: int = 10000) -> dict[str, Any]:
    """Each evaluation reads URL/title/content atomically in the current document.

    Only transient navigation errors and empty bodies are retried. Ongoing DOM
    animation doesn't invalidate a read. This never refreshes or replays actions.
    """
    async with asyncio.timeout(timeout_ms / 1000):
        while True:
            try:
                data: dict[str, Any] = await page.evaluate(READ)
                data['status'] = classify(data['url'], data['title'], data['content'])
                if data['status'] != 'EMPTY':
                    data['trust'] = 'untrusted_web_payload'
                    data['observed_at'] = datetime.now(timezone.utc).isoformat()
                    data['task_completed'] = False
                    return data
            except Error as exc:
                if page.is_closed() or 'EXTRACTION_LIMIT' in str(exc):
                    raise
            await asyncio.sleep(.25)

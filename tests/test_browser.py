import os

import httpx
import pytest

from app.core.config import Settings
from app.core.exceptions import BridgeError
from app.models.request import FetchRequest
from app.services.browser import BrowserFetcher
from app.services.fetcher import HTTPFetcher
from app.services.manager import RequestManager
from tests.test_fetcher import PublicPolicy, response


async def test_browser_is_opt_in():
    manager = RequestManager(Settings(respect_robots=False))
    try:
        with pytest.raises(BridgeError) as error:
            await manager.fetch(FetchRequest(url="https://example.com", render="browser"))
        assert error.value.code == "BROWSER_DISABLED"
    finally:
        await manager.close()


@pytest.mark.skipif(os.getenv("BRIDGE_TEST_BROWSER") != "1", reason="Opt-in Chromium integration test")
async def test_browser_renders_javascript_and_blocks_private_fetch():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return response(b"""<html><body><main id="main"></main><script>
            document.querySelector('#main').innerHTML = '<p>Rendered research findings.</p>';
            fetch('http://127.0.0.1/private').catch(() => {});
            </script></body></html>""")

    settings = Settings(browser_enabled=True, respect_robots=False)
    gateway = HTTPFetcher(settings, PublicPolicy(), httpx.MockTransport(handler))
    try:
        result = await BrowserFetcher(settings, gateway).fetch("https://example.com/")
        assert "<p>Rendered research findings.</p>" in result.html
        assert result.method == "browser"
        assert len(calls) == 1
    finally:
        await gateway.close()

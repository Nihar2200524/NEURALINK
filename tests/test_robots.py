import httpx
import pytest

from app.core.config import Settings
from app.core.exceptions import BridgeError
from app.services.fetcher import HTTPFetcher
from app.services.robots import RobotsPolicy
from tests.test_fetcher import PublicPolicy, response


async def test_robots_deny_allow_and_cache():
    calls = []

    def handler(request):
        calls.append(request)
        return response(b"User-agent: *\nDisallow: /private\nAllow: /public")

    fetcher = HTTPFetcher(Settings(), PublicPolicy(), httpx.MockTransport(handler))
    try:
        robots = RobotsPolicy(fetcher, "AIWebBridge/0.1")
        await robots.check("https://example.com/public")
        with pytest.raises(BridgeError) as error:
            await robots.check("https://example.com/private")
        assert error.value.code == "ROBOTS_DENIED"
        assert len(calls) == 1
    finally:
        await fetcher.close()

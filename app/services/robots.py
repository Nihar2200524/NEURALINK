from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from app.core.exceptions import BridgeError
from app.services.cache import MemoryCache
from app.services.fetcher import HTTPFetcher


class RobotsPolicy:
    def __init__(self, fetcher: HTTPFetcher, user_agent: str):
        self.fetcher, self.user_agent = fetcher, user_agent
        self.cache = MemoryCache(300, 128)

    async def check(self, url: str) -> None:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        rules = await self.cache.get(origin)
        if rules is None:
            document = await self.fetcher.retrieve(
                origin + "/robots.txt", None, check_robots=False, accept_errors=True
            )
            if document.status in {404, 410}:
                rules = ""
            elif document.status >= 400:
                raise BridgeError("ROBOTS_DENIED", "Robots policy could not be verified.", 403)
            else:
                rules = document.html
            await self.cache.set(origin, rules)
        parser = RobotFileParser()
        parser.parse(rules.splitlines())
        if not parser.can_fetch(self.user_agent, url):
            raise BridgeError("ROBOTS_DENIED", "The target robots.txt disallows this path.", 403)

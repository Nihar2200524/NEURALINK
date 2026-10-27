"""Deterministic demos: python -m examples.demo. No internet or running server required."""

import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.services.fetcher import HTTPFetcher
from app.services.manager import RequestManager
from app.utils.urls import normalize_url

FIXTURES = Path(__file__).parent / "pages"


class DemoPolicy:
    async def resolve(self, url):
        return normalize_url(url), "93.184.216.34"


class DemoStream(httpx.AsyncByteStream):
    def __init__(self, data):
        self.data = data

    async def __aiter__(self):
        yield self.data


def main():
    def handler(request):
        name = request.url.path.strip("/") or "news"
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            stream=DemoStream((FIXTURES / f"{name}.html").read_bytes()),
        )

    settings = Settings(respect_robots=False)
    manager = RequestManager(settings, HTTPFetcher(settings, DemoPolicy(), httpx.MockTransport(handler)))
    results = {}
    with TestClient(create_app(settings, manager)) as client:
        for name in ("news", "documentation", "encyclopedia"):
            results[name] = client.post("/v1/fetch", json={"url": f"https://example.com/{name}"}).json()
        results["query"] = client.post(
            "/v1/fetch", json={"url": "https://example.com/news", "query": "battery findings"}
        ).json()
        results["batch"] = client.post(
            "/v1/batch", json={"urls": ["https://example.com/news", "https://example.com/documentation"]}
        ).json()
        results["cached"] = client.post("/v1/fetch", json={"url": "https://example.com/news"}).json()
    (Path(__file__).parent / "responses.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    for name in ("news", "documentation", "encyclopedia", "query", "cached"):
        stats = results[name]["optimization"]
        print(
            f"{name}: {stats['estimated_raw_tokens']} -> {stats['estimated_returned_tokens']} estimated tokens "
            f"({stats['token_reduction_percent']}% reduction); cached={results[name]['metadata']['cached']}"
        )


if __name__ == "__main__":
    main()

import httpx
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.services.fetcher import HTTPFetcher
from app.services.manager import RequestManager
from tests.test_fetcher import PublicPolicy, response


def test_health():
    with TestClient(create_app()) as client:
        assert client.get("/health").json() == {"status": "ok", "service": "ai-web-bridge"}


def test_extract_validation_markdown_and_limits():
    with TestClient(create_app(Settings(max_request_bytes=1000))) as client:
        result = client.post("/v1/extract", json={"html": "<h1>Research</h1><p>New AI findings.</p>"})
        assert result.status_code == 200
        assert "AI findings" in result.json()["content"]["main_text"]
        assert result.headers["x-request-id"]
        assert client.post("/v1/fetch", json={"url": "x", "format": "xml"}).status_code == 422
        assert (
            client.post("/v1/extract", json={"html": "<p>Text</p>", "format": "markdown"})
            .headers["content-type"]
            .startswith("text/markdown")
        )
        assert client.post("/v1/extract", json={"html": "x" * 2000}).status_code == 413


def test_fetch_cache_and_batch():
    calls = []

    def handler(request):
        calls.append(request)
        return response(b"<title>Article</title><main><p>Research findings about AI.</p></main>")

    settings = Settings(respect_robots=False)
    manager = RequestManager(settings, HTTPFetcher(settings, PublicPolicy(), httpx.MockTransport(handler)))
    with TestClient(create_app(settings, manager)) as client:
        first = client.post("/v1/fetch", json={"url": "https://example.com"}).json()
        second = client.post("/v1/fetch", json={"url": "https://example.com"}).json()
        assert first["metadata"]["cached"] is False
        assert second["metadata"]["cached"] is True
        assert len(calls) == 1
        batch = client.post("/v1/batch", json={"urls": ["https://example.com", "http://127.0.0.1"]}).json()
        assert batch["results"][1]["error"]["code"] == "BLOCKED_URL"


def test_no_store_responses_are_not_cached():
    calls = []

    def handler(request):
        calls.append(request)
        return response(b"<p>Uncached content.</p>", **{"cache-control": "no-store"})

    settings = Settings(respect_robots=False)
    manager = RequestManager(settings, HTTPFetcher(settings, PublicPolicy(), httpx.MockTransport(handler)))
    with TestClient(create_app(settings, manager)) as client:
        for _ in range(2):
            result = client.post("/v1/fetch", json={"url": "https://example.com"})
            assert result.json()["metadata"]["cached"] is False
        assert len(calls) == 2

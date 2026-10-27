"""Run against a running local bridge: python examples/basic_request.py."""

import httpx

with httpx.Client(base_url="http://localhost:8000", timeout=30) as client:
    response = client.post("/v1/fetch", json={"url": "https://example.com"})
    response.raise_for_status()
    print(response.json())

"""Query mode and partial-success batch consumption without an AI dependency."""

import asyncio

import httpx


async def main():
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=60) as client:
        result = await client.post(
            "/v1/batch",
            json={
                "urls": ["https://example.com", "https://www.python.org/about/"],
                "query": "Python programming",
                "max_content_length": 2000,
            },
        )
        result.raise_for_status()
        for item in result.json()["results"]:
            if "error" in item:
                print(item["url"], item["error"]["code"])
            else:
                print(item["result"]["content"]["main_text"])


if __name__ == "__main__":
    asyncio.run(main())

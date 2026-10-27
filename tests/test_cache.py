import asyncio

from app.services.cache import MemoryCache


async def test_ttl_eviction_and_copy():
    cache = MemoryCache(0.01, 1)
    await cache.set("a", {"x": 1})
    value = await cache.get("a")
    value["x"] = 2
    assert (await cache.get("a"))["x"] == 1
    await cache.set("b", 3)
    assert await cache.get("a") is None
    await asyncio.sleep(0.02)
    assert await cache.get("b") is None

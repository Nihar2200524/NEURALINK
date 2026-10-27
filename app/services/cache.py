import copy
import time
from collections import OrderedDict
from typing import Any, Protocol


class Cache(Protocol):
    async def get(self, key: str) -> Any | None: ...
    async def set(self, key: str, value: Any) -> None: ...


class MemoryCache:
    def __init__(self, ttl: float = 300, capacity: int = 128):
        self.ttl, self.capacity = ttl, capacity
        self.items: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    async def get(self, key: str) -> Any | None:
        item = self.items.get(key)
        if item is None:
            return None
        expires, value = item
        if expires <= time.monotonic():
            del self.items[key]
            return None
        self.items.move_to_end(key)
        return copy.deepcopy(value)

    async def set(self, key: str, value: Any) -> None:
        self.items[key] = (time.monotonic() + self.ttl, copy.deepcopy(value))
        self.items.move_to_end(key)
        while len(self.items) > self.capacity:
            self.items.popitem(last=False)

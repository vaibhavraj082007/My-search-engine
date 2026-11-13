"""Shared async cache with optional Redis and single-flight de-duplication.

Local development works with an in-process LRU/TTL cache. Set REDIS_URL to
share cached search payloads across workers and instances.
"""

import asyncio
import json
import os
import time
from collections import OrderedDict
from typing import Any, Awaitable, Callable

try:  # Redis is optional; the app runs without it.
    import redis.asyncio as redis_async
except Exception:  # pragma: no cover - exercised only without the package
    redis_async = None

REDIS_URL = os.getenv("REDIS_URL", "").strip()
CACHE_MAX_ITEMS = int(os.getenv("CACHE_MAX_ITEMS", "5000"))
DEFAULT_TTL = int(os.getenv("SEARCH_CACHE_TTL", "300"))

ShouldCache = Callable[[Any], bool] | None


class Cache:
    def __init__(self, max_items: int = CACHE_MAX_ITEMS, ttl: int = DEFAULT_TTL):
        self.max_items = max_items
        self.ttl = ttl
        self.redis = None
        self._memory: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._memory_lock = asyncio.Lock()
        self._inflight: dict[str, asyncio.Task] = {}
        self._inflight_lock = asyncio.Lock()

    async def start(self) -> None:
        if not REDIS_URL or redis_async is None:
            return
        try:
            self.redis = redis_async.from_url(
                REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
                health_check_interval=30,
            )
            await self.redis.ping()
        except Exception:
            self.redis = None

    async def close(self) -> None:
        if self.redis is not None:
            try:
                await self.redis.aclose()
            except Exception:
                pass
            self.redis = None

    async def get(self, key: str) -> Any | None:
        if self.redis is not None:
            try:
                raw = await self.redis.get(key)
                if raw is not None:
                    return json.loads(raw)
            except Exception:
                pass

        async with self._memory_lock:
            item = self._memory.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at < time.monotonic():
                self._memory.pop(key, None)
                return None
            self._memory.move_to_end(key)
            return value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        ttl = self.ttl if ttl is None else ttl
        if self.redis is not None:
            try:
                await self.redis.set(key, json.dumps(value, separators=(",", ":")), ex=ttl)
                return
            except Exception:
                pass

        async with self._memory_lock:
            self._memory[key] = (time.monotonic() + ttl, value)
            self._memory.move_to_end(key)
            while len(self._memory) > self.max_items:
                self._memory.popitem(last=False)

    async def _compute(
        self,
        key: str,
        factory: Callable[[], Awaitable[Any]],
        ttl: int | None,
        should_cache: ShouldCache,
        negative_ttl: int,
    ) -> Any:
        try:
            value = await factory()
            if value is not None:
                if should_cache is None or should_cache(value):
                    await self.set(key, value, ttl)
                elif negative_ttl > 0:
                    # Cache empty/failed results briefly. This keeps a broken
                    # upstream from being hammered by every request while still
                    # letting the page recover quickly.
                    await self.set(key, value, negative_ttl)
            return value
        finally:
            async with self._inflight_lock:
                if self._inflight.get(key) is asyncio.current_task():
                    self._inflight.pop(key, None)

    async def get_or_set(
        self,
        key: str,
        factory: Callable[[], Awaitable[Any]],
        ttl: int | None = None,
        should_cache: ShouldCache = None,
        negative_ttl: int = 0,
    ) -> tuple[Any, bool]:
        """Return (value, cache_hit). Concurrent misses share one computation."""
        cached = await self.get(key)
        if cached is not None:
            return cached, True

        async with self._inflight_lock:
            task = self._inflight.get(key)
            if task is None:
                task = asyncio.create_task(
                    self._compute(key, factory, ttl, should_cache, negative_ttl)
                )
                self._inflight[key] = task

        # shield keeps the shared computation alive if this request is cancelled
        return await asyncio.shield(task), False


cache = Cache()

"""Per-client request limiting with optional Redis sharing."""

import os
import time
from collections import defaultdict

RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "120"))
WINDOW_SECONDS = 60


class RateLimiter:
    def __init__(self, limit: int = RATE_LIMIT_PER_MINUTE, window: int = WINDOW_SECONDS):
        self.limit = limit
        self.window = window
        self.redis = None  # set by main.py after the shared cache starts
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._last_prune = time.monotonic()

    def enabled(self) -> bool:
        return self.limit > 0

    async def allow(self, key: str) -> bool:
        if not self.enabled():
            return True

        if self.redis is not None:
            try:
                bucket = int(time.time() // self.window)
                redis_key = f"rl:{key}:{bucket}"
                count = await self.redis.incr(redis_key)
                if count == 1:
                    await self.redis.expire(redis_key, self.window + 1)
                return count <= self.limit
            except Exception:
                pass  # fall back to local limiting

        now = time.monotonic()
        cutoff = now - self.window
        hits = [stamp for stamp in self._hits.get(key, []) if stamp >= cutoff]
        if len(hits) >= self.limit:
            self._hits[key] = hits
            return False
        hits.append(now)
        self._hits[key] = hits

        if now - self._last_prune > self.window * 2:
            self._last_prune = now
            for existing_key, stamps in list(self._hits.items()):
                if not stamps or stamps[-1] < cutoff:
                    self._hits.pop(existing_key, None)

        # Hard cap so a spray of unique client IPs cannot grow memory forever.
        if len(self._hits) > 200_000:
            for existing_key in list(self._hits.keys())[:100_000]:
                self._hits.pop(existing_key, None)
        return True


limiter = RateLimiter()

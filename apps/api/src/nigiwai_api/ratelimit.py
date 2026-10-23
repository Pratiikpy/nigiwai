"""Sliding-window rate limits in Redis, plus single-use nonce storage. Keys carry only hashes and expire."""

from __future__ import annotations

import time
from typing import Any

# Atomic sliding window: drop old entries, count, add the new one when allowed. Returns {allowed, count}.
_SLIDING = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count >= limit then return {0, count} end
redis.call('ZADD', key, now, ARGV[4])
redis.call('EXPIRE', key, math.ceil(window) + 1)
return {1, count + 1}
"""


class RateLimiter:
    def __init__(self, redis: Any) -> None:
        self._redis = redis

    async def allow(self, key: str, limit: int, window_s: float) -> bool:
        now = time.time()
        member = f"{now}:{time.monotonic_ns()}"
        allowed, _ = await self._redis.eval(_SLIDING, 1, f"rl:{key}", now, window_s, limit, member)
        return bool(int(allowed))

    async def check_all(self, rules: list[tuple[str, int, float]]) -> str | None:
        """Apply several limits; return the name of the first one exceeded, else None."""
        for key, limit, window in rules:
            if not await self.allow(key, limit, window):
                return key.split(":", 1)[0]
        return None

    async def consume_nonce(self, nonce_id: str, ttl_s: int) -> bool:
        """True the first time a nonce id is used, False on a replay."""
        return bool(await self._redis.set(f"nonce:{nonce_id}", "1", ex=ttl_s, nx=True))

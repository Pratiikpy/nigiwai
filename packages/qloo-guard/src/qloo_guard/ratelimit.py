"""Rate limiting and the circuit breaker.

`TokenBucket` is the in-process limiter. `RedisTokenBucket` is the shared one for several API instances: a Lua
script keeps the bucket atomic. Waiting is bounded per purpose: a picker request gives up after 1.5 s so the
local index can answer alone (ARCHITECTURE 3.4).
"""

from __future__ import annotations

import asyncio
import random
import time
from collections import deque
from collections.abc import Callable
from typing import Any, Protocol

from .errors import BudgetExhausted, CircuitOpen

MAX_WAIT_S: dict[str, float] = {"picker": 1.5, "card": 3.0, "ask": 10.0, "fit": 10.0, "board": 20.0}
DEFAULT_MAX_WAIT_S = 30.0


class RateLimiter(Protocol):
    async def acquire(self, purpose: str) -> None: ...


class TokenBucket:
    def __init__(
        self, rate_per_second: float, burst: int, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._rate = rate_per_second
        self._burst = float(burst)
        self._tokens = float(burst)
        self._clock = clock
        self._updated = clock()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self._burst, self._tokens + (now - self._updated) * self._rate)
        self._updated = now

    async def acquire(self, purpose: str) -> None:
        max_wait = MAX_WAIT_S.get(purpose, DEFAULT_MAX_WAIT_S)
        deadline = self._clock() + max_wait
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                need = (1.0 - self._tokens) / self._rate
            if self._clock() + need > deadline:
                raise BudgetExhausted("rate", f"waited more than {max_wait}s for a Qloo slot")
            await asyncio.sleep(need + random.uniform(0, 0.02))  # noqa: S311 - jitter, not security


_LUA = """
local key = KEYS[1]
local rate = tonumber(ARGV[1])
local burst = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then tokens = burst; ts = now end
tokens = math.min(burst, tokens + (now - ts) * rate)
local wait = 0
if tokens >= 1 then
  tokens = tokens - 1
else
  wait = (1 - tokens) / rate
end
redis.call('HSET', key, 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', key, 60)
return tostring(wait)
"""


class RedisTokenBucket:
    """Shared bucket. `redis` is a redis.asyncio.Redis. The key is namespaced by the API key fingerprint."""

    def __init__(self, redis: Any, key: str, rate_per_second: float, burst: int) -> None:
        self._redis = redis
        self._key = key
        self._rate = rate_per_second
        self._burst = burst

    async def acquire(self, purpose: str) -> None:
        max_wait = MAX_WAIT_S.get(purpose, DEFAULT_MAX_WAIT_S)
        deadline = time.time() + max_wait
        while True:
            wait = float(
                await self._redis.eval(_LUA, 1, self._key, self._rate, self._burst, time.time())
            )
            if wait <= 0:
                return
            if time.time() + wait > deadline:
                raise BudgetExhausted("rate", f"waited more than {max_wait}s for a Qloo slot")
            await asyncio.sleep(wait + random.uniform(0, 0.02))  # noqa: S311


class CircuitBreaker:
    """Opens after `threshold` failures in `window_s`, stays open for `cooldown_s` (ARCHITECTURE 4.6)."""

    def __init__(
        self,
        threshold: int = 5,
        window_s: float = 30.0,
        cooldown_s: float = 15.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._threshold = threshold
        self._window = window_s
        self._cooldown = cooldown_s
        self._clock = clock
        self._failures: deque[float] = deque()
        self._open_until = 0.0

    def check(self) -> None:
        if self._clock() < self._open_until:
            raise CircuitOpen("qloo circuit is open")

    def success(self) -> None:
        self._failures.clear()

    def failure(self) -> None:
        now = self._clock()
        self._failures.append(now)
        while self._failures and now - self._failures[0] > self._window:
            self._failures.popleft()
        if len(self._failures) >= self._threshold:
            self._open_until = now + self._cooldown
            self._failures.clear()

    @property
    def is_open(self) -> bool:
        return self._clock() < self._open_until

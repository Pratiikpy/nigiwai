"""Budgets (ARCHITECTURE 3.4): per-trace caps and a monthly ledger with a share per purpose class.

Semantics: reserve before a call; a cache hit refunds; a failed call counts. When a class runs out, only cached
answers are served. The picker may borrow from the incident floor.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from .config import QlooConfig
from .errors import BudgetExhausted

# Per-trace call caps by purpose (proof F and ARCHITECTURE 3.4 and 4.2).
TRACE_CAPS: dict[str, int] = {
    "ask": 13,  # 12 model-callable plus 1 system call
    "card": 3,
    "fit": 4,
    "picker": 20,
    "board": 40,
    "tribes": 10,
    "eval": 400,
    "canary": 12,
    "lineup": 60,
    "system": 10,
}


@dataclass
class BudgetHandle:
    """Per-trace counter. Reserve before a live call; refund when the answer came from the cache."""

    cap: int
    used: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def for_purpose(cls, purpose: str) -> BudgetHandle:
        return cls(cap=TRACE_CAPS.get(purpose, 10))

    def reserve(self, n: int = 1) -> None:
        with self._lock:
            if self.used + n > self.cap:
                raise BudgetExhausted("trace", f"{self.used}/{self.cap} calls used")
            self.used += n

    def refund(self, n: int = 1) -> None:
        with self._lock:
            self.used = max(0, self.used - n)

    @property
    def remaining(self) -> int:
        return max(0, self.cap - self.used)


class QuotaLedger(Protocol):
    def record(self, purpose: str, *, live: bool, month_remaining: int | None) -> None: ...

    def live_calls(self, purpose: str) -> int: ...

    @property
    def month_remaining_last(self) -> int | None: ...


class MemoryQuotaLedger:
    """In-process ledger. The API replaces it with a Postgres-backed one (table `quota_ledger`)."""

    def __init__(self) -> None:
        self._live: dict[str, int] = defaultdict(int)
        self._cached: dict[str, int] = defaultdict(int)
        self._remaining: int | None = None
        self._month = _month()

    def _roll(self) -> None:
        if _month() != self._month:
            self._month = _month()
            self._live.clear()
            self._cached.clear()

    def record(self, purpose: str, *, live: bool, month_remaining: int | None) -> None:
        self._roll()
        if live:
            self._live[purpose] += 1
        else:
            self._cached[purpose] += 1
        if month_remaining is not None:
            self._remaining = month_remaining

    def live_calls(self, purpose: str) -> int:
        self._roll()
        return self._live[purpose]

    @property
    def month_remaining_last(self) -> int | None:
        return self._remaining


def _month() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


class QuotaManager:
    """Decides whether a live call may proceed for a purpose class."""

    def __init__(self, config: QlooConfig, ledger: QuotaLedger) -> None:
        self._config = config
        self._ledger = ledger

    def check(self, purpose: str) -> None:
        remaining = self._ledger.month_remaining_last
        if (
            remaining is not None
            and remaining < self._config.month_floor
            and purpose not in ("system", "canary")
        ):
            raise BudgetExhausted(
                "month", f"{remaining} calls left, floor {self._config.month_floor}"
            )
        share = self._config.class_shares.get(purpose, 0.04)
        cap = int(share * self._config.month_limit)
        if purpose == "picker":  # may borrow the incident floor
            cap += int(self._config.class_shares.get("system", 0.04) * self._config.month_limit)
        if self._ledger.live_calls(purpose) >= cap:
            raise BudgetExhausted("class", f"{purpose} used {cap} of its monthly share")

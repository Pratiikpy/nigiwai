"""Exceptions raised by the Guard. Rule rejections are errors the caller can show; transport errors carry the status."""

from __future__ import annotations


class GuardError(Exception):
    """Base class for every error the Guard raises on purpose."""


class RuleRejected(GuardError):
    """A pre-rule refused the request before any network call."""

    def __init__(self, rule: str, message: str, allowed: tuple[str, ...] = ()) -> None:
        super().__init__(f"{rule}: {message}")
        self.rule = rule
        self.message = message
        self.allowed = allowed


class BudgetExhausted(GuardError):
    """The per-trace, per-class or per-month budget has no room for another live call."""

    def __init__(self, scope: str, detail: str = "") -> None:
        super().__init__(f"budget exhausted ({scope}) {detail}".strip())
        self.scope = scope


class ReplayMiss(GuardError):
    """Replay mode was asked for a response that was never recorded. It never falls through to live."""

    def __init__(self, cache_key: str) -> None:
        super().__init__(f"no recorded response for {cache_key[:16]}")
        self.cache_key = cache_key


class TransportError(GuardError):
    """The network call failed or returned an error status."""

    def __init__(
        self, message: str, status: int | None = None, *, retryable: bool = False, body: str = ""
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable
        self.body = body[:300]


class QlooAuthError(TransportError):
    """401 or 403: the key, host or endpoint access is wrong. Never retried."""


class CircuitOpen(GuardError):
    """Too many recent failures: calls are refused for a short cool-down."""

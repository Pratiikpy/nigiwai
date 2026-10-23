"""Build a Guard from configuration. In-memory defaults serve tests and single-process tools; the API passes
Postgres-backed stores, a Redis limiter and its own recorder."""

from __future__ import annotations

from .budget import MemoryQuotaLedger, QuotaLedger, QuotaManager
from .cache import MemoryStore, ResponseStore
from .config import QlooConfig, key_fingerprint, read_key, resolve_harness_command
from .errors import GuardError
from .guard import QlooGuard
from .ratelimit import RateLimiter, TokenBucket
from .registry import EntityRegistry, MemoryRegistry
from .trace import MemoryRecorder, TraceRecorder
from .transports import HarnessTransport, RestTransport, Transport


def build_guard(
    config: QlooConfig,
    *,
    store: ResponseStore | None = None,
    registry: EntityRegistry | None = None,
    ledger: QuotaLedger | None = None,
    limiter: RateLimiter | None = None,
    recorder: TraceRecorder | None = None,
    transports: list[Transport] | None = None,
    api_key: str | None = None,
) -> QlooGuard:
    key = api_key or read_key(config)
    if transports is None:
        if config.mode == "replay":
            transports = []  # replay never goes to the network
        else:
            if not key:
                raise GuardError("no Qloo key: set QLOO_API_KEY or NIGIWAI_QLOO_KEY_FILE")
            rest = RestTransport(config.base_url, key, config.timeout_s)
            harness = HarnessTransport(
                config.base_url,
                key,
                resolve_harness_command(config),
                config.timeout_s,
                config.harness_home,
            )
            transports = [harness, rest] if config.transport == "harness" else [rest]
    ledger = ledger or MemoryQuotaLedger()
    return QlooGuard(
        config=config,
        transports=transports,
        store=store or MemoryStore(),
        registry=registry or MemoryRegistry(),
        quota=QuotaManager(config, ledger),
        limiter=limiter or TokenBucket(config.rate_per_second, config.burst),
        recorder=recorder or MemoryRecorder(),
        ledger=ledger,
        key_fingerprint=key_fingerprint(key) if key else "",
    )

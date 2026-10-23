"""Trace recorder (ARCHITECTURE 3.7): one record per call, with ordered result ids and a key fingerprint only."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from .models import CacheState, Mode, Purpose, QlooWarning, RuleEvent


@dataclass
class CallContext:
    trace_id: UUID
    purpose: Purpose
    mode: Mode = "live"
    tenant_id: UUID | None = None
    budget: Any = None  # BudgetHandle; typed loosely to avoid a cycle
    # For global jobs that call with ids not yet in the registry (canary, eval). Production paths leave this False.
    allow_unregistered_ids: bool = False
    probe: bool = False
    place_listed: bool = False


@dataclass
class CallRecord:
    call_id: UUID
    trace_id: UUID
    tenant_id: UUID | None
    purpose: str
    endpoint: str
    params: list[tuple[str, str]]
    status: str
    http_status: int | None
    transport: str
    cache: CacheState
    latency_ms: int
    result_entity_ids: list[str]
    warnings: list[QlooWarning]
    rule_events: list[RuleEvent]
    key_fingerprint: str
    host: str
    guard_version: str
    cache_key: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class TraceRecorder(Protocol):
    async def record(self, call: CallRecord) -> None: ...


class MemoryRecorder:
    def __init__(self) -> None:
        self.calls: list[CallRecord] = []

    async def record(self, call: CallRecord) -> None:
        self.calls.append(call)

    def for_trace(self, trace_id: UUID) -> list[CallRecord]:
        return [c for c in self.calls if c.trace_id == trace_id]

"""The Qloo Guard pipeline (ARCHITECTURE 3.1).

Typed request, pre-rules, cache lookup (mandatory hit in replay), single-flight, budget reserve, quota check,
rate limit, transport with retries and fallback, classification, persistence, post-rules, trace.
"""

from __future__ import annotations

import asyncio
import dataclasses
import random
import time
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import UUID, uuid4

from .budget import BudgetHandle, QuotaManager
from .cache import ResponseStore, StoredResponse, ttl_for
from .canonical import GUARD_RULES_VERSION, cache_key
from .config import QlooConfig
from .errors import (
    BudgetExhausted,
    CircuitOpen,
    QlooAuthError,
    ReplayMiss,
    RuleRejected,
    TransportError,
)
from .models import (
    CompareResult,
    DemographicsItem,
    Entity,
    EntityType,
    GuardResult,
    GuardStatus,
    QlooWarning,
    RuleEvent,
    Tag,
    is_forbidden_type,
)
from .parse import (
    entities_from_body,
    minimise_places,
    parse_compare,
    parse_demographics,
    parse_tags,
    parse_warnings,
)
from .post import PostResult, apply_insights_post, dedupe
from .ratelimit import CircuitBreaker, RateLimiter
from .registry import EntityRegistry, RegistryEntry, entry_from_entity, has_forbidden_type
from .requests import (
    INSIGHTS_BY_TYPE,
    CompareRequest,
    DemographicsRequest,
    EntitiesRequest,
    InsightsRequest,
    Params,
    SearchRequest,
    TagsRequest,
)
from .trace import CallContext, CallRecord, TraceRecorder
from .transports.base import RawResponse, Transport


@dataclass
class _Fetched:
    body: Any = None
    http_status: int | None = None
    cache: str = "miss"
    transport: str = "none"
    latency_ms: int = 0
    status: GuardStatus = "ok"
    events: list[RuleEvent] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    cache_key: str = ""


def _rule_event(rule: str, effect: str, detail: str) -> RuleEvent:
    return RuleEvent(rule=rule, stage="pre", effect=effect, detail=detail)  # type: ignore[arg-type]


class QlooGuard:
    def __init__(
        self,
        *,
        config: QlooConfig,
        transports: list[Transport],
        store: ResponseStore,
        registry: EntityRegistry,
        quota: QuotaManager,
        limiter: RateLimiter,
        recorder: TraceRecorder,
        ledger: Any,
        key_fingerprint: str = "",
        breaker: CircuitBreaker | None = None,
        clock: Any = time.time,
        sleep: Any = asyncio.sleep,
    ) -> None:
        self.config = config
        self._transports = transports
        self._store = store
        self.registry = registry
        self._quota = quota
        self._limiter = limiter
        self._recorder = recorder
        self._ledger = ledger
        self._fingerprint = key_fingerprint
        self._breaker = breaker or CircuitBreaker()
        self._clock = clock
        self._sleep = sleep
        self._inflight: dict[str, asyncio.Future[_Fetched]] = {}

    # ------------------------------------------------------------------------------------------ helpers
    def new_context(
        self, purpose: str, *, tenant_id: UUID | None = None, mode: str | None = None
    ) -> CallContext:
        return CallContext(
            trace_id=uuid4(),
            purpose=purpose,  # type: ignore[arg-type]
            mode=(mode or self.config.mode),  # type: ignore[arg-type]
            tenant_id=tenant_id,
            budget=BudgetHandle.for_purpose(purpose),
        )

    async def aclose(self) -> None:
        for t in self._transports:
            await t.aclose()

    # ------------------------------------------------------------------------------------------ pre-rules
    async def _check_ids(self, ids: tuple[str, ...], ctx: CallContext, *, as_signal: bool) -> None:
        for entity_id in ids:
            entry = await self.registry.get(entity_id)
            if entry is None:
                if ctx.allow_unregistered_ids:
                    continue
                raise RuleRejected(
                    "T13-unregistered",
                    f"entity {entity_id} was never resolved; search for it first",
                )
            if has_forbidden_type(entry):
                raise RuleRejected(
                    "T12-person",
                    f"{entry.name or entity_id} is a person-like entity and cannot be used",
                )
            if (
                as_signal
                and not ctx.probe
                and not ctx.allow_unregistered_ids
                and entry.eligible is not True
            ):
                state = (
                    "was rejected by insights"
                    if entry.eligible is False
                    else "has not passed the eligibility probe"
                )
                raise RuleRejected("T13-ineligible", f"{entry.name or entity_id} {state}")

    async def _register(self, entities: list[Entity]) -> None:
        for e in entities:
            if any(is_forbidden_type(t) for t in e.types):
                continue
            await self.registry.put(entry_from_entity(e))

    # ------------------------------------------------------------------------------------------ fetch
    async def _fetch(self, path: str, params: Params, ctx: CallContext) -> _Fetched:
        key = cache_key(self.config.host, path, params)
        now = self._clock()
        stored = await self._store.get(key)
        if ctx.mode == "replay":
            if stored is None:
                raise ReplayMiss(key)
            self._ledger.record(ctx.purpose, live=False, month_remaining=None)
            return _Fetched(
                body=stored.body,
                http_status=stored.status,
                cache="replay",
                transport=stored.transport,
                cache_key=key,
            )
        if stored is not None and stored.fresh(now):
            self._ledger.record(ctx.purpose, live=False, month_remaining=None)
            return _Fetched(
                body=stored.body,
                http_status=stored.status,
                cache="hit",
                transport=stored.transport,
                cache_key=key,
            )

        pending = self._inflight.get(key)
        if pending is not None:  # single-flight: identical request already in the air
            shared = await pending
            return dataclasses.replace(shared, cache="hit")

        fut: asyncio.Future[_Fetched] = asyncio.get_running_loop().create_future()
        self._inflight[key] = fut
        try:
            result = await self._live(path, params, ctx, key, stale=stored)
            fut.set_result(result)
            return result
        except BaseException as exc:
            if not fut.done():
                fut.set_exception(exc)
                fut.exception()  # mark retrieved so asyncio does not warn when nobody else awaits it
            raise
        finally:
            self._inflight.pop(key, None)

    async def _live(
        self, path: str, params: Params, ctx: CallContext, key: str, *, stale: StoredResponse | None
    ) -> _Fetched:
        now = self._clock()
        # Stale-while-revalidate: the picker would rather show a 2x-TTL answer than wait on Qloo.
        if (
            stale is not None
            and ctx.purpose == "picker"
            and stale.stale_usable(now)
            and self._breaker.is_open
        ):
            return _Fetched(
                body=stale.body,
                http_status=stale.status,
                cache="stale",
                transport=stale.transport,
                cache_key=key,
            )

        reserved = False
        try:
            if ctx.budget is not None:
                ctx.budget.reserve()
                reserved = True
            self._quota.check(ctx.purpose)
            self._breaker.check()
            await self._limiter.acquire(ctx.purpose)
        except BudgetExhausted as exc:
            if reserved:
                ctx.budget.refund()
            if stale is not None and stale.stale_usable(now) and ctx.purpose == "picker":
                return _Fetched(
                    body=stale.body,
                    http_status=stale.status,
                    cache="stale",
                    transport=stale.transport,
                    cache_key=key,
                )
            return _Fetched(
                status="budget_exhausted",
                events=[_rule_event("budget", "rejected", str(exc))],
                cache_key=key,
            )
        except CircuitOpen as exc:
            if reserved:
                ctx.budget.refund()
            if stale is not None and stale.stale_usable(now):
                return _Fetched(
                    body=stale.body,
                    http_status=stale.status,
                    cache="stale",
                    transport=stale.transport,
                    cache_key=key,
                )
            return _Fetched(
                status="unavailable",
                events=[_rule_event("circuit", "rejected", str(exc))],
                cache_key=key,
            )

        order = [t for t in self._transports if t.supports(path, params)]
        if ctx.purpose in self.config.rest_first_purposes:
            order.sort(
                key=lambda t: t.name != "rest"
            )  # stable: REST first, the rest keep their order
        if not order:
            return _Fetched(
                status="unavailable",
                events=[_rule_event("transport", "rejected", f"no transport carries {path}")],
                cache_key=key,
            )

        raw: RawResponse | None = None
        last: TransportError | None = None
        fallback_note = ""
        for i, transport in enumerate(order):
            try:
                raw = await self._call(transport, path, params)
                if i > 0:
                    fallback_note = f"served by {transport.name} after {order[0].name} failed"
                break
            except QlooAuthError:
                self._ledger.record(ctx.purpose, live=True, month_remaining=None)
                raise
            except TransportError as exc:
                last = exc
                self._breaker.failure()
        if raw is None:
            self._ledger.record(ctx.purpose, live=True, month_remaining=None)
            detail = str(last) if last else "no response"
            return _Fetched(
                status="unavailable",
                events=[_rule_event("transport", "rejected", detail)],
                cache_key=key,
            )

        remaining = _int_header(raw.headers.get("x-month-ratelimit-remaining"))
        self._ledger.record(ctx.purpose, live=True, month_remaining=remaining)
        events = [_rule_event("transport", "info", fallback_note)] if fallback_note else []

        if raw.status in (429,) or raw.status >= 500:
            self._breaker.failure()
            return _Fetched(
                status="unavailable",
                http_status=raw.status,
                transport=raw.transport,
                latency_ms=raw.elapsed_ms,
                events=[*events, _rule_event("qloo-status", "rejected", f"HTTP {raw.status}")],
                headers=raw.headers,
                cache_key=key,
            )
        self._breaker.success()
        raw = dataclasses.replace(raw, body=minimise_places(raw.body))
        if raw.status in (200, 400, 404):
            ttl = ttl_for(path, params, probe=ctx.probe, place_listed=ctx.place_listed)
            await self._store.put(
                StoredResponse(
                    cache_key=key,
                    host=self.config.host,
                    endpoint=path,
                    params=list(params),
                    status=raw.status,
                    body=raw.body,
                    headers=raw.headers,
                    transport=raw.transport,
                    fetched_at=now,
                    expires_at=now + ttl,
                    guard_version=GUARD_RULES_VERSION,
                )
            )
        return _Fetched(
            body=raw.body,
            http_status=raw.status,
            cache="miss",
            transport=raw.transport,
            latency_ms=raw.elapsed_ms,
            events=events,
            headers=raw.headers,
            cache_key=key,
        )

    async def _call(self, transport: Transport, path: str, params: Params) -> RawResponse:
        """One transport, with the retry policy of rule G28: 429 waits (at most twice), 5xx or a timeout retries once."""
        rate_waits = 0
        server_retries = 0
        while True:
            try:
                raw = await transport.get(path, params)
            except TransportError as exc:
                if exc.retryable and server_retries < 1:
                    server_retries += 1
                    await self._sleep(1.0)
                    continue
                raise
            if raw.status == 429 and rate_waits < 2:
                rate_waits += 1
                reset = _int_header(raw.headers.get("x-second-ratelimit-reset")) or 1
                await self._sleep(min(reset, 5) + random.uniform(0.05, 0.25))  # noqa: S311
                continue
            if raw.status >= 500 and server_retries < 1:
                server_retries += 1
                await self._sleep(1.0)
                continue
            return raw

    # ------------------------------------------------------------------------------------------ recording
    async def _record(
        self,
        ctx: CallContext,
        path: str,
        params: Params,
        f: _Fetched,
        ids: list[str],
        events: list[RuleEvent],
        warnings: list[QlooWarning],
        status: GuardStatus,
        call_id: UUID,
    ) -> None:
        await self._recorder.record(
            CallRecord(
                call_id=call_id,
                trace_id=ctx.trace_id,
                tenant_id=ctx.tenant_id,
                purpose=ctx.purpose,
                endpoint=path,
                params=list(params),
                status=status,
                http_status=f.http_status,
                transport=f.transport,
                cache=f.cache,  # type: ignore[arg-type]
                latency_ms=f.latency_ms,
                result_entity_ids=ids,
                warnings=warnings,
                rule_events=events,
                key_fingerprint=self._fingerprint,
                host=self.config.host,
                guard_version=GUARD_RULES_VERSION,
                cache_key=f.cache_key,
            )
        )

    async def _finish(
        self,
        ctx: CallContext,
        path: str,
        params: Params,
        f: _Fetched,
        items: Any,
        ids: list[str],
        events: list[RuleEvent],
        warnings: list[QlooWarning],
        status: GuardStatus,
        empty: Any,
    ) -> GuardResult[Any]:
        call_id = uuid4()
        await self._record(ctx, path, params, f, ids, events, warnings, status, call_id)
        return GuardResult(
            status=status,
            items=items if status in ("ok", "degraded", "empty") else empty,
            call_id=call_id,
            cache=f.cache,  # type: ignore[arg-type]
            transport=f.transport,
            rule_events=events,
            warnings=warnings,
            latency_ms=f.latency_ms,
            result_entity_ids=ids,
        )

    async def _rejected(
        self, ctx: CallContext, path: str, params: Params, exc: RuleRejected, empty: Any
    ) -> GuardResult[Any]:
        f = _Fetched(status="rejected", cache="bypass")
        ev = [_rule_event(exc.rule, "rejected", exc.message)]
        return await self._finish(ctx, path, params, f, empty, [], ev, [], "rejected", empty)

    def _http_failure(self, f: _Fetched) -> tuple[GuardStatus, list[RuleEvent]] | None:
        """Map a non-200 outcome to a status. Returns None when the body can be parsed."""
        if f.status in ("budget_exhausted", "unavailable"):
            return f.status, f.events
        if f.http_status == 400:
            return "rejected", [
                *f.events,
                _rule_event("qloo-400", "rejected", "Qloo refused the request"),
            ]
        if f.http_status == 404:
            return "empty", f.events
        if f.http_status is not None and f.http_status != 200:
            return "unavailable", [
                *f.events,
                _rule_event("qloo-status", "rejected", f"HTTP {f.http_status}"),
            ]
        return None

    # ------------------------------------------------------------------------------------------ endpoints
    async def search(self, req: SearchRequest, ctx: CallContext) -> GuardResult[list[Entity]]:
        path, params = req.endpoint()
        f = await self._fetch(path, params, ctx)
        fail = self._http_failure(f)
        if fail is not None:
            return await self._finish(ctx, path, params, f, [], [], fail[1], [], fail[0], [])
        items = entities_from_body(path, f.body)
        events = list(f.events)
        wanted = {t.value for t in req.types}
        kept = [e for e in items if not e.types or wanted & set(e.types)]
        if len(kept) != len(items):
            events.append(
                RuleEvent(
                    rule="T18-type",
                    stage="post",
                    effect="dropped",
                    detail="not a requested type",
                    count=len(items) - len(kept),
                )
            )
        kept, ev = dedupe(kept, set())
        events += ev
        kept = [e for e in kept if not any(is_forbidden_type(t) for t in e.types)]
        await self._register(kept)
        status: GuardStatus = (
            "ok" if kept else "empty"
        )  # trap 14: a miss is `empty`, never an error
        return await self._finish(
            ctx, path, params, f, kept, [e.entity_id for e in kept], events, [], status, []
        )

    async def entities(self, req: EntitiesRequest, ctx: CallContext) -> GuardResult[list[Entity]]:
        path, params = req.endpoint()
        f = await self._fetch(path, params, ctx)
        fail = self._http_failure(f)
        if fail is not None:
            return await self._finish(ctx, path, params, f, [], [], fail[1], [], fail[0], [])
        items = [
            e
            for e in entities_from_body(path, f.body)
            if not any(is_forbidden_type(t) for t in e.types)
        ]
        await self._register(items)
        status: GuardStatus = "ok" if items else "empty"
        return await self._finish(
            ctx,
            path,
            params,
            f,
            items,
            [e.entity_id for e in items],
            list(f.events),
            [],
            status,
            [],
        )

    async def tags(self, req: TagsRequest, ctx: CallContext) -> GuardResult[list[Tag]]:
        path, params = req.endpoint()
        f = await self._fetch(path, params, ctx)
        fail = self._http_failure(f)
        if fail is not None:
            return await self._finish(ctx, path, params, f, [], [], fail[1], [], fail[0], [])
        tags = parse_tags(f.body)
        return await self._finish(
            ctx, path, params, f, tags, [], list(f.events), [], "ok" if tags else "empty", []
        )

    async def compare(
        self, req: CompareRequest, ctx: CallContext
    ) -> GuardResult[CompareResult | None]:
        path, params = req.endpoint()
        try:
            await self._check_ids(req.a + req.b, ctx, as_signal=True)
        except RuleRejected as exc:
            return await self._rejected(ctx, path, params, exc, None)
        f = await self._fetch(path, params, ctx)
        fail = self._http_failure(f)
        if fail is not None:
            return await self._finish(ctx, path, params, f, None, [], fail[1], [], fail[0], None)
        result = parse_compare(f.body)
        # Rule G22: drop country-namespace tags and cut to the top 20 shared tags.
        shared = tuple(
            t
            for t in result.shared_tags
            if "country" not in (t.type or "") and "country" not in t.tag_id
        )[:20]
        events = list(f.events)
        if len(shared) != len(result.shared_tags):
            events.append(
                RuleEvent(
                    rule="G22",
                    stage="post",
                    effect="dropped",
                    detail="country or surplus tags",
                    count=len(result.shared_tags) - len(shared),
                )
            )
        cleaned = CompareResult(shared_tags=shared, a_tags=result.a_tags, b_tags=result.b_tags)
        return await self._finish(
            ctx, path, params, f, cleaned, [], events, [], "ok" if shared else "empty", None
        )

    async def demographics(
        self, req: DemographicsRequest, ctx: CallContext
    ) -> GuardResult[list[DemographicsItem]]:
        path, params = req.endpoint()
        try:
            await self._check_ids(req.signal_entities, ctx, as_signal=True)
        except RuleRejected as exc:
            return await self._rejected(ctx, path, params, exc, [])
        f = await self._fetch(path, params, ctx)
        fail = self._http_failure(f)
        if fail is not None:
            return await self._finish(ctx, path, params, f, [], [], fail[1], [], fail[0], [])
        items = parse_demographics(f.body)
        return await self._finish(
            ctx,
            path,
            params,
            f,
            items,
            [i.entity_id for i in items],
            list(f.events),
            parse_warnings(f.body),
            "ok" if items else "empty",
            [],
        )

    async def insights(self, req: InsightsRequest, ctx: CallContext) -> GuardResult[list[Entity]]:
        path, params = req.endpoint()
        try:
            await self._check_ids(req.signal_entities, ctx, as_signal=True)
            await self._check_ids(req.results_entities + req.exclude_entities, ctx, as_signal=False)
        except RuleRejected as exc:
            return await self._rejected(ctx, path, params, exc, [])
        f = await self._fetch(path, params, ctx)
        fail = self._http_failure(f)
        if fail is not None:
            return await self._finish(ctx, path, params, f, [], [], fail[1], [], fail[0], [])
        raw_items = entities_from_body(path, f.body)
        warnings = parse_warnings(f.body)
        post: PostResult = apply_insights_post(req, raw_items, warnings)
        await self._register(post.items)
        events = list(f.events) + post.events
        if f.transport == "harness" and req.signal_entities:
            events.append(
                _rule_event("D5-harness-no-warnings", "info", "harness output carries no warnings")
            )
        return await self._finish(
            ctx,
            path,
            params,
            f,
            post.items,
            [e.entity_id for e in post.items],
            events,
            warnings,
            post.status,
            [],
        )

    async def probe_eligibility(self, entity: Entity, ctx: CallContext) -> bool | None:
        """Trap 13: ask insights for one result seeded with this entity. Returns None when Qloo could not answer."""
        if any(is_forbidden_type(t) for t in entity.types):
            await self.registry.put(
                RegistryEntry(entity.entity_id, entity.types, entity.name, eligible=False)
            )
            return False
        try:
            etype = EntityType(entity.primary_type)
        except ValueError:
            await self.registry.put(
                RegistryEntry(entity.entity_id, entity.types, entity.name, eligible=False)
            )
            return False
        cls = INSIGHTS_BY_TYPE.get(etype)
        if cls is None or etype is EntityType.PLACE:
            await self.registry.put(
                RegistryEntry(entity.entity_id, entity.types, entity.name, eligible=True)
            )
            return True  # places are context, not seeds; they are never probed
        probe_ctx = dataclasses.replace(ctx, probe=True, allow_unregistered_ids=True)
        req = cast(InsightsRequest, cls(signal_entities=(entity.entity_id,), take=1))
        res = await self.insights(req, probe_ctx)
        if res.status in ("ok", "degraded", "empty"):
            eligible: bool | None = True
        elif res.status == "rejected":
            eligible = False
        else:
            eligible = None
        await self.registry.put(
            RegistryEntry(entity.entity_id, entity.types, entity.name, eligible=eligible)
        )
        return eligible

    async def ensure_eligible(
        self, entity_ids: tuple[str, ...], ctx: CallContext
    ) -> dict[str, bool | None]:
        """Probe every known entity that has not been probed yet (trap 13), so it can be used as a signal. Entities the
        registry has never seen are reported as None and are not probed. Returns each entity's eligibility."""
        out: dict[str, bool | None] = {}
        for entity_id in entity_ids:
            entry = await self.registry.get(entity_id)
            if entry is None:
                out[entity_id] = None
            elif entry.eligible is not None:
                out[entity_id] = entry.eligible
            else:
                probe = Entity(entity_id=entity_id, name=entry.name or entity_id, types=entry.types)
                out[entity_id] = await self.probe_eligibility(probe, ctx)
        return out


def _int_header(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None

"""Postgres-backed implementations of the Guard's protocols: the private response cache, the entity registry,
the quota ledger and the trace recorder. Qloo response bodies are compressed and encrypted at rest."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from collections import defaultdict
from datetime import UTC, datetime

import zstandard
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from qloo_guard import (
    MemoryQuotaLedger,
    RegistryEntry,
    StoredResponse,
)
from qloo_guard.trace import CallRecord
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ..db import transaction


def derive_cache_key(secret_key: str) -> bytes:
    """A 256-bit key for the private cache, derived from the application secret (HKDF-SHA256)."""
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=b"nigiwai-qloo-cache-v1"
    ).derive(secret_key.encode("utf-8"))


class PgResponseStore:
    def __init__(self, engine: AsyncEngine, secret_key: str) -> None:
        self._engine = engine
        self._aead = AESGCM(derive_cache_key(secret_key))
        self._zc = zstandard.ZstdCompressor(level=6)
        self._zd = zstandard.ZstdDecompressor()

    def _seal(self, body: object) -> bytes:
        raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        nonce = os.urandom(12)
        return nonce + self._aead.encrypt(nonce, self._zc.compress(raw), None)

    def _open(self, blob: bytes) -> object:
        nonce, sealed = blob[:12], blob[12:]
        return json.loads(
            self._zd.decompress(self._aead.decrypt(nonce, sealed, None)).decode("utf-8")
        )

    async def get(self, cache_key: str) -> StoredResponse | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT host, endpoint, params, status, body, headers, transport, guard_version,"
                        " extract(epoch FROM fetched_at) AS f, extract(epoch FROM expires_at) AS e"
                        " FROM qloo_response WHERE cache_key = :k"
                    ),
                    {"k": cache_key},
                )
            ).first()
        if row is None:
            return None
        try:
            body = self._open(bytes(row.body)) if row.body is not None else None
        except Exception:
            return None
        return StoredResponse(
            cache_key=cache_key,
            host=row.host,
            endpoint=row.endpoint,
            params=[(k, v) for k, v in row.params],
            status=row.status,
            body=body,
            headers=dict(row.headers or {}),
            transport=row.transport,
            fetched_at=float(row.f),
            expires_at=float(row.e),
            guard_version=row.guard_version,
        )

    async def put(self, response: StoredResponse) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO qloo_response (cache_key, host, endpoint, params, status, body, headers, transport,"
                    " fetched_at, expires_at, guard_version)"
                    " VALUES (:k, :host, :endpoint, CAST(:params AS jsonb), :status, :body, CAST(:headers AS jsonb),"
                    " :transport, to_timestamp(:f), to_timestamp(:e), :gv)"
                    " ON CONFLICT (cache_key) DO UPDATE SET status = EXCLUDED.status, body = EXCLUDED.body,"
                    " headers = EXCLUDED.headers, transport = EXCLUDED.transport, fetched_at = EXCLUDED.fetched_at,"
                    " expires_at = EXCLUDED.expires_at, guard_version = EXCLUDED.guard_version"
                ),
                {
                    "k": response.cache_key,
                    "host": response.host,
                    "endpoint": response.endpoint,
                    "params": json.dumps([list(p) for p in response.params]),
                    "status": response.status,
                    "body": self._seal(response.body) if response.body is not None else None,
                    "headers": json.dumps(response.headers),
                    "transport": response.transport,
                    "f": response.fetched_at,
                    "e": response.expires_at,
                    "gv": response.guard_version,
                },
            )


class PgRegistry:
    """`qloo_entity` as the Guard's registry. `put` merges: it never clears a known eligibility or tags."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get(self, entity_id: str) -> RegistryEntry | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT types, name_nfc, insights_eligible, popularity, props, musicbrainz_id, tags"
                        " FROM qloo_entity WHERE entity_id = :i"
                    ),
                    {"i": entity_id},
                )
            ).first()
        if row is None:
            return None
        props = row.props or {}
        return RegistryEntry(
            entity_id=entity_id,
            types=tuple(row.types),
            name=row.name_nfc,
            eligible=row.insights_eligible,
            popularity=row.popularity,
            description=props.get("description"),
            release_year=props.get("release_year"),
            musicbrainz_id=row.musicbrainz_id,
            tags=tuple((t[0], t[1], t[2]) for t in (row.tags or [])),
        )

    async def put(self, entry: RegistryEntry) -> None:
        primary = entry.types[0] if entry.types else "unknown"
        props = {
            k: v
            for k, v in (("description", entry.description), ("release_year", entry.release_year))
            if v is not None
        }
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO qloo_entity (entity_id, type, types, name_nfc, insights_eligible, eligibility_checked_at,"
                    " popularity, props, musicbrainz_id, tags)"
                    " VALUES (:i, :t, :ts, :n, CAST(:el AS boolean),"
                    " CASE WHEN CAST(:el AS boolean) IS NULL THEN NULL ELSE now() END,"
                    " :pop, CAST(:props AS jsonb), :mb, CAST(:tags AS jsonb))"
                    " ON CONFLICT (entity_id) DO UPDATE SET"
                    "  type = EXCLUDED.type, types = EXCLUDED.types,"
                    "  name_nfc = CASE WHEN EXCLUDED.name_nfc = '' THEN qloo_entity.name_nfc ELSE EXCLUDED.name_nfc END,"
                    "  insights_eligible = COALESCE(EXCLUDED.insights_eligible, qloo_entity.insights_eligible),"
                    "  eligibility_checked_at = CASE WHEN EXCLUDED.insights_eligible IS NULL THEN"
                    "    qloo_entity.eligibility_checked_at ELSE now() END,"
                    "  popularity = COALESCE(EXCLUDED.popularity, qloo_entity.popularity),"
                    "  props = qloo_entity.props || EXCLUDED.props,"
                    "  musicbrainz_id = COALESCE(EXCLUDED.musicbrainz_id, qloo_entity.musicbrainz_id),"
                    "  tags = CASE WHEN EXCLUDED.tags = '[]'::jsonb THEN qloo_entity.tags ELSE EXCLUDED.tags END,"
                    "  updated_at = now()"
                ),
                {
                    "i": entry.entity_id,
                    "t": primary,
                    "ts": list(entry.types),
                    "n": entry.name or "",
                    "el": entry.eligible,
                    "pop": entry.popularity,
                    "props": json.dumps(props),
                    "mb": entry.musicbrainz_id,
                    "tags": json.dumps([list(t) for t in entry.tags]),
                },
            )


class PgBackedLedger(MemoryQuotaLedger):
    """In-process counters (the Guard reads them synchronously) flushed to `quota_ledger`. The month's live total
    and Qloo's own `x-month-ratelimit-remaining` are loaded at start-up, so a restart does not reset them."""

    def __init__(self, engine: AsyncEngine, fingerprint: str) -> None:
        super().__init__()
        self._engine = engine
        self._fp = fingerprint
        self._pending_live: dict[str, int] = defaultdict(int)
        self._pending_cached: dict[str, int] = defaultdict(int)

    def record(self, purpose: str, *, live: bool, month_remaining: int | None) -> None:
        super().record(purpose, live=live, month_remaining=month_remaining)
        (self._pending_live if live else self._pending_cached)[purpose] += 1

    async def load(self) -> None:
        month = datetime.now(UTC).strftime("%Y-%m")
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT purpose, sum(calls_live) AS live, max(month_remaining_last) FILTER (WHERE true) AS rem"
                        " FROM quota_ledger WHERE key_fingerprint = :f AND to_char(day, 'YYYY-MM') = :m GROUP BY purpose"
                    ),
                    {"f": self._fp, "m": month},
                )
            ).all()
            last = (
                await conn.execute(
                    text(
                        "SELECT month_remaining_last FROM quota_ledger WHERE key_fingerprint = :f"
                        " AND month_remaining_last IS NOT NULL ORDER BY day DESC LIMIT 1"
                    ),
                    {"f": self._fp},
                )
            ).first()
        for r in rows:
            self._live[r.purpose] = int(r.live or 0)
        if last is not None:
            self._remaining = int(last[0])

    async def flush(self) -> None:
        if not (self._pending_live or self._pending_cached):
            return
        live, cached = dict(self._pending_live), dict(self._pending_cached)
        self._pending_live.clear()
        self._pending_cached.clear()
        async with self._engine.begin() as conn:
            for purpose in set(live) | set(cached):
                await conn.execute(
                    text(
                        "INSERT INTO quota_ledger (day, key_fingerprint, purpose, calls_live, calls_cached, month_remaining_last)"
                        " VALUES (CURRENT_DATE, :f, :p, :l, :c, :r)"
                        " ON CONFLICT (day, key_fingerprint, purpose) DO UPDATE SET"
                        "  calls_live = quota_ledger.calls_live + EXCLUDED.calls_live,"
                        "  calls_cached = quota_ledger.calls_cached + EXCLUDED.calls_cached,"
                        "  month_remaining_last = COALESCE(EXCLUDED.month_remaining_last, quota_ledger.month_remaining_last)"
                    ),
                    {
                        "f": self._fp,
                        "p": purpose,
                        "l": live.get(purpose, 0),
                        "c": cached.get(purpose, 0),
                        "r": self._remaining,
                    },
                )

    async def run_flusher(self, every_s: float = 10.0) -> None:
        while True:
            await asyncio.sleep(every_s)
            # A failed flush retries on the next tick; the counters are still in memory.
            with contextlib.suppress(Exception):
                await self.flush()


class PgRecorder:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def record(self, call: CallRecord) -> None:
        # Tenant calls are written under that tenant's scope so the row-level policies see them; calls with no
        # tenant (canaries, global jobs) are insert-only because no tenant session may read them back.
        async with transaction(self._engine, tenant_id=call.tenant_id) as conn:
            await conn.execute(
                text(
                    "INSERT INTO trace (id, tenant_id, kind, guard_version) VALUES (:t, :tenant, :kind, :gv)"
                    " ON CONFLICT (id) DO NOTHING"
                ),
                {
                    "t": call.trace_id,
                    "tenant": call.tenant_id,
                    "kind": call.purpose,
                    "gv": call.guard_version,
                },
            )
            if call.tenant_id is not None:
                await conn.execute(
                    text("UPDATE trace SET calls_used = calls_used + 1 WHERE id = :t"),
                    {"t": call.trace_id},
                )
            await conn.execute(
                text(
                    "INSERT INTO qloo_call (id, trace_id, tenant_id, purpose, endpoint, params, status, http_status,"
                    " transport, cache, latency_ms, result_entity_ids, warnings, rule_events, key_fingerprint, host,"
                    " guard_version, cache_key)"
                    " VALUES (:id, :trace, :tenant, :purpose, :endpoint, CAST(:params AS jsonb), :status, :http,"
                    " :transport, :cache, :latency, :ids, CAST(:warnings AS jsonb), CAST(:events AS jsonb), :fp, :host,"
                    " :gv, :ck)"
                ),
                {
                    "id": call.call_id,
                    "trace": call.trace_id,
                    "tenant": call.tenant_id,
                    "purpose": call.purpose,
                    "endpoint": call.endpoint,
                    "params": json.dumps([list(p) for p in call.params]),
                    "status": call.status,
                    "http": call.http_status,
                    "transport": call.transport,
                    "cache": call.cache,
                    "latency": call.latency_ms,
                    "ids": list(call.result_entity_ids),
                    "warnings": json.dumps([w.model_dump() for w in call.warnings]),
                    "events": json.dumps([e.model_dump() for e in call.rule_events]),
                    "fp": call.key_fingerprint,
                    "host": call.host,
                    "gv": call.guard_version,
                    "ck": call.cache_key,
                },
            )

"""The survey's entity picker (M3).

Typing searches Nigiwai's own index of entities Qloo has already returned (fast, no Qloo call), and falls back to a
live Qloo search only when the local index has too few matches. Choosing an entity runs the eligibility probe once
(trap 13), so a pick that Qloo's insights would reject is refused while the guest can still choose another.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Literal
from uuid import UUID, uuid4

from qloo_guard import (
    PICKER_TYPES,
    CallContext,
    Entity,
    EntityType,
    QlooGuard,
    SearchRequest,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ..schemas import PickerItem, PickerOut

LOCAL_ENOUGH = 6  # matches from the local index that make a live search unnecessary
RESULT_LIMIT = 8
MIN_CHARS = 2
MAX_CHARS = 80
ALLOWED = {t.value for t in PICKER_TYPES}

TYPE_URN = {
    "artist": EntityType.ARTIST,
    "movie": EntityType.MOVIE,
    "tv_show": EntityType.TV_SHOW,
    "book": EntityType.BOOK,
    "brand": EntityType.BRAND,
    "podcast": EntityType.PODCAST,
    "videogame": EntityType.VIDEOGAME,
}


def normalise(query: str) -> str:
    """NFC, control and invisible characters replaced by spaces (Postgres refuses NUL), whitespace collapsed."""
    cleaned = "".join(
        " " if unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co") else ch
        for ch in unicodedata.normalize("NFC", query)
    )
    return " ".join(cleaned.split())[:MAX_CHARS]


def _like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _short_type(urn: str) -> str:
    return urn.rsplit(":", 1)[-1]


@dataclass(frozen=True)
class Selection:
    entity_id: str
    eligible: bool | None
    type: str | None = None


class PickerService:
    def __init__(self, engine: AsyncEngine, guard: QlooGuard | None) -> None:
        self._engine = engine
        self._guard = guard

    # ------------------------------------------------------------------------------------------ search
    async def search(
        self, query: str, types: list[str], *, tenant_id: UUID | None, allow_live: bool
    ) -> PickerOut:
        q = normalise(query)
        if len(q) < MIN_CHARS:
            return PickerOut(items=[], source="none", message=f"Type at least {MIN_CHARS} letters.")
        urns = [TYPE_URN[t].value for t in types if t in TYPE_URN]
        if not urns:
            return PickerOut(items=[], source="none", message="Nothing to search for.")
        items = await self._local(q, urns)
        source: Literal["local", "qloo", "cache", "none"] = "local"
        message: str | None = None
        if len(items) < LOCAL_ENOUGH and allow_live and self._guard is not None:
            live, cache_state, note = await self._live(q, types, tenant_id)
            live = await self._without_ineligible(live)
            seen = {i.entity_id for i in items}
            fresh = [i for i in live if i.entity_id not in seen]
            if fresh:
                items = (items + fresh)[:RESULT_LIMIT]
                source = "cache" if cache_state in ("hit", "stale", "replay") else "qloo"
            message = note
        if not items and message is None:
            message = "No match yet. Try another spelling, or choose something else you love."
        return PickerOut(items=items, source=source if items else "none", message=message)

    async def _local(self, q: str, urns: list[str]) -> list[PickerItem]:
        like = _like_escape(q.lower())
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT entity_id, name_nfc, type, props, disambiguation,"
                        "  (lower(name_nfc) LIKE :prefix ESCAPE '\\') AS is_prefix,"
                        "  similarity(lower(name_nfc), :q) AS sim"
                        " FROM qloo_entity"
                        " WHERE type = ANY(:types) AND insights_eligible IS NOT FALSE"
                        "  AND (lower(name_nfc) LIKE :prefix ESCAPE '\\' OR lower(name_nfc) LIKE :inside ESCAPE '\\'"
                        "       OR lower(name_nfc) % :q)"
                        " ORDER BY is_prefix DESC, sim DESC, popularity DESC NULLS LAST, name_nfc"
                        " LIMIT :n"
                    ),
                    {
                        "prefix": like + "%",
                        "inside": "% " + like + "%",
                        "q": q.lower(),
                        "types": urns,
                        "n": RESULT_LIMIT,
                    },
                )
            ).all()
        return [
            self._item(r.entity_id, r.name_nfc, r.type, r.props or {}, r.disambiguation)
            for r in rows
        ]

    async def _live(
        self, q: str, types: list[str], tenant_id: UUID | None
    ) -> tuple[list[PickerItem], str, str | None]:
        assert self._guard is not None
        request = SearchRequest(
            query=q, types=tuple(TYPE_URN[t] for t in types if t in TYPE_URN), take=RESULT_LIMIT
        )
        ctx = CallContext(trace_id=uuid4(), purpose="picker", tenant_id=tenant_id)
        result = await self._guard.search(request, ctx)
        if not result.ok:
            if result.status == "empty":
                return [], result.cache, None
            return (
                [],
                result.cache,
                "Live search is unavailable right now; showing saved matches only.",
            )
        return (
            [
                self._item(
                    e.entity_id,
                    e.name,
                    e.primary_type,
                    {"description": e.description, "release_year": e.release_year},
                    None,
                )
                for e in result.items
                if e.primary_type in ALLOWED
            ],
            result.cache,
            None,
        )

    async def _without_ineligible(self, items: list[PickerItem]) -> list[PickerItem]:
        """Insights refuses some entities that search returns (trap 13). Once one is known, it is never offered."""
        if not items:
            return items
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT entity_id FROM qloo_entity WHERE entity_id = ANY(:ids) AND insights_eligible IS FALSE"
                    ),
                    {"ids": [i.entity_id for i in items]},
                )
            ).all()
        refused = {r.entity_id for r in rows}
        return [i for i in items if i.entity_id not in refused]

    @staticmethod
    def _item(
        entity_id: str,
        name: str,
        type_urn: str,
        props: dict[str, object],
        disambiguation: str | None,
    ) -> PickerItem:
        year = props.get("release_year")
        description = props.get("description")
        return PickerItem(
            entity_id=entity_id,
            name=name,
            type=_short_type(type_urn),
            year=year if isinstance(year, int) else None,
            description=(
                description[:140] if isinstance(description, str) and description else None
            ),
            disambiguation=disambiguation,
        )

    # ------------------------------------------------------------------------------------------ select
    async def select(self, entity_id: str, *, tenant_id: UUID | None) -> Selection | None:
        """Resolve a chosen entity and probe it once. None means the id is not one the picker ever offered."""
        if self._guard is None:
            row = await self._row(entity_id)
            if row is None:
                return None
            return Selection(entity_id, row[2], _short_type(row[1]))
        entry = await self._guard.registry.get(entity_id)
        if entry is None or not entry.types or entry.types[0] not in ALLOWED:
            return None
        if entry.eligible is not None:
            return Selection(entity_id, entry.eligible, _short_type(entry.types[0]))
        entity = Entity(entity_id=entity_id, name=entry.name or entity_id, types=entry.types)
        ctx = CallContext(trace_id=uuid4(), purpose="picker", tenant_id=tenant_id)
        eligible = await self._guard.probe_eligibility(entity, ctx)
        return Selection(entity_id, eligible, _short_type(entry.types[0]))

    async def _row(self, entity_id: str) -> tuple[str, str, bool | None] | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT entity_id, type, insights_eligible FROM qloo_entity WHERE entity_id = :i"
                    ),
                    {"i": entity_id},
                )
            ).first()
        if row is None or row.type not in ALLOWED:
            return None
        return (row.entity_id, row.type, row.insights_eligible)

    async def resolve_picks(
        self, entity_ids: list[str]
    ) -> dict[str, tuple[str, bool | None]] | None:
        """Entity id -> (full type urn, eligibility) for every id, or None when any id was never offered by the picker
        or is not a pickable type. Only registered entities can be stored as picks."""
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT entity_id, type, insights_eligible FROM qloo_entity WHERE entity_id = ANY(:ids)"
                    ),
                    {"ids": entity_ids},
                )
            ).all()
        found = {r.entity_id: (r.type, r.insights_eligible) for r in rows}
        if set(found) != set(entity_ids) or any(t not in ALLOWED for t, _ in found.values()):
            return None
        return found

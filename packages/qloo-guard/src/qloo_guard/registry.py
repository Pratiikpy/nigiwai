"""Entity registry: which entity ids the Guard knows, their types and whether insights accepts them.

Rule T12 (no person seeds) and T13 (an entity that search finds may still be rejected by insights, for example
a popular novel) are enforced against this registry before any call is made. Ids enter the registry from search
results, from /entities, or from the picker after an eligibility probe.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import Entity, is_forbidden_type


@dataclass
class RegistryEntry:
    entity_id: str
    types: tuple[str, ...]
    name: str = ""
    eligible: bool | None = None  # None = not probed yet


class EntityRegistry(Protocol):
    async def get(self, entity_id: str) -> RegistryEntry | None: ...

    async def put(self, entry: RegistryEntry) -> None: ...


class MemoryRegistry:
    def __init__(self) -> None:
        self._items: dict[str, RegistryEntry] = {}

    async def get(self, entity_id: str) -> RegistryEntry | None:
        return self._items.get(entity_id)

    async def put(self, entry: RegistryEntry) -> None:
        old = self._items.get(entry.entity_id)
        if old is not None and entry.eligible is None:
            entry.eligible = old.eligible
        self._items[entry.entity_id] = entry


def entry_from_entity(e: Entity, eligible: bool | None = None) -> RegistryEntry:
    return RegistryEntry(entity_id=e.entity_id, types=e.types, name=e.name, eligible=eligible)


def has_forbidden_type(entry: RegistryEntry) -> bool:
    return any(is_forbidden_type(t) for t in entry.types)

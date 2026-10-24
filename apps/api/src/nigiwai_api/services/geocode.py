"""Finding a neighbourhood on the map from the name a guest typed (the optional district answer).

OpenStreetMap's Nominatim, used the way its policy asks: at most one request a second, a User-Agent that says who is
asking, and every answer cached so the same name is never asked twice. It is only ever asked about a district that at
least ten guests named (a smaller one is never shown, so it is never looked up), and the search is bounded to the area
around the venue so a common name finds the neighbourhood next door and not one on another continent.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import unicodedata
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

CACHE_TTL = timedelta(days=90)
BOX_DEGREES = 0.35  # about 35 km each way: a city and its surroundings


def normalise_district(name: str) -> str:
    """The key a district is counted and looked up under: case, accents and spacing do not make a new district."""
    base = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().casefold()
    return " ".join("".join(c if c.isalnum() else " " for c in base).split())


class Geocoder:
    _lock = asyncio.Lock()
    _last = 0.0
    INTERVAL = 1.1  # seconds between requests: the policy allows one a second

    def __init__(
        self,
        engine: AsyncEngine,
        base_url: str,
        contact: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._engine = engine
        self._base = base_url.rstrip("/")
        self._headers = {"User-Agent": f"Nigiwai/0.1 ({contact})", "Accept": "application/json"}
        self._client = client or httpx.AsyncClient(timeout=15.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def key(district: str, near: tuple[float, float]) -> str:
        box = f"{round(near[0], 1)},{round(near[1], 1)}"
        return hashlib.sha256(f"geo|{normalise_district(district)}|{box}".encode()).hexdigest()

    async def cached(self, district: str, near: tuple[float, float]) -> dict[str, Any] | None:
        """What is already known about this district near this venue: a place, or that none was found. None if unasked."""
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT body, fetched_at FROM external_cache WHERE key = :k AND source = 'nominatim'"
                    ),
                    {"k": self.key(district, near)},
                )
            ).first()
        if row is None or datetime.now(UTC) - row.fetched_at > CACHE_TTL:
            return None
        return dict(row.body)

    async def _get(self, params: dict[str, str]) -> Any:
        """One search request, one at a time and no faster than the policy allows. Raises httpx.HTTPError."""
        async with self._lock:
            wait = self.INTERVAL - (time.monotonic() - Geocoder._last)
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                response = await self._client.get(
                    f"{self._base}/search", params=params, headers=self._headers
                )
            finally:
                Geocoder._last = time.monotonic()
        response.raise_for_status()
        return response.json()

    async def search(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        """Places matching an address an owner typed: [{label, lat, lon}], best first. Asked only when the owner presses
        the button (never as they type), and every answer is cached. Raises httpx.HTTPError when it could not be asked."""
        q = " ".join(query.split())[:200]
        key = hashlib.sha256(f"geo-search|{limit}|{normalise_district(q)}".encode()).hexdigest()
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT body, fetched_at FROM external_cache WHERE key = :k AND source = 'nominatim'"
                    ),
                    {"k": key},
                )
            ).first()
        if row is not None and datetime.now(UTC) - row.fetched_at <= CACHE_TTL:
            return list(row.body.get("places", []))
        hits = await self._get(
            {"q": q, "format": "jsonv2", "limit": str(limit), "addressdetails": "0"}
        )
        places: list[dict[str, Any]] = []
        for hit in hits if isinstance(hits, list) else []:
            try:
                lat, lon = float(hit["lat"]), float(hit["lon"])
                label = " ".join(str(hit.get("display_name") or hit.get("name") or "").split())[
                    :200
                ]
            except (KeyError, TypeError, ValueError):
                continue
            if label and -90 <= lat <= 90 and -180 <= lon <= 180:
                places.append({"label": label, "lat": lat, "lon": lon})
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO external_cache (key, source, status, body) VALUES (:k, 'nominatim', 200, CAST(:b AS jsonb))"
                    " ON CONFLICT (key) DO UPDATE SET body = EXCLUDED.body, fetched_at = now()"
                ),
                {"k": key, "b": json.dumps({"places": places})},
            )
        return places

    async def locate(self, district: str, near: tuple[float, float]) -> dict[str, Any] | None:
        """Ask Nominatim. Returns {lat, lon, label} or None when it knows no such place near the venue. Raises
        httpx.HTTPError when it could not be asked (nothing is cached then, so the next request tries again)."""
        q = " ".join(district.split())[:80]
        lat, lon = near
        params = {
            "q": q,
            "format": "jsonv2",
            "limit": "1",
            "viewbox": f"{lon - BOX_DEGREES},{lat + BOX_DEGREES},{lon + BOX_DEGREES},{lat - BOX_DEGREES}",
            "bounded": "1",
        }
        hits = await self._get(params)
        found: dict[str, Any] = {"found": False}
        if isinstance(hits, list) and hits:
            hit = hits[0]
            try:
                found = {
                    "found": True,
                    "lat": float(hit["lat"]),
                    "lon": float(hit["lon"]),
                    "label": str(hit.get("name") or hit.get("display_name") or q)[:80],
                }
            except (KeyError, TypeError, ValueError):
                found = {"found": False}
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO external_cache (key, source, status, body) VALUES (:k, 'nominatim', 200, CAST(:b AS jsonb))"
                    " ON CONFLICT (key) DO UPDATE SET body = EXCLUDED.body, fetched_at = now()"
                ),
                {"k": self.key(district, near), "b": json.dumps(found)},
            )
        return found if found["found"] else None

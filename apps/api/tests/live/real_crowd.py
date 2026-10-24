"""Shared by the live tests that need a crowd of real artists: resolve them through the survey picker (real Qloo), then
plant responses from them through the same database function the survey uses. The survey endpoints are exercised by the
other live tests; here the responses go in directly, because one QR point holds back responses beyond 40 in ten
minutes (a rule the survey rightly has)."""

from __future__ import annotations

import random
import uuid
from typing import Any

import psycopg
from harness import Venue, World

CROWDS: dict[str, list[str]] = {
    "pop": [
        "Dua Lipa",
        "Olivia Rodrigo",
        "Billie Eilish",
        "Sabrina Carpenter",
        "Charli XCX",
        "Gracie Abrams",
        "Doja Cat",
        "Taylor Swift",
    ],
    "crooners": [
        "Frank Sinatra",
        "Bing Crosby",
        "Dean Martin",
        "Tony Bennett",
        "Nat King Cole",
        "Perry Como",
        "Ella Fitzgerald",
        "Louis Armstrong",
    ],
    "metal": [
        "Metallica",
        "Iron Maiden",
        "Slayer",
        "Pantera",
        "Black Sabbath",
        "Judas Priest",
        "Megadeth",
        "Anthrax",
    ],
}


async def resolve(world: World, venue: Venue, crowds: dict[str, list[str]]) -> dict[str, list[str]]:
    """Entity ids of the artists that Qloo matches by exact name and accepts as seeds, a sitting per crowd (a sitting
    may make 20 live searches)."""
    ids: dict[str, list[str]] = {name: [] for name in crowds}
    for n, (crowd, acts) in enumerate(crowds.items()):
        guest = world.client()
        guest.headers["x-forwarded-for"] = f"10.8.0.{n + 1}"
        page = (await guest.get(f"/v1/public/survey/{venue.token}")).json()
        for act in acts:
            found = (
                await guest.post(
                    "/v1/public/picker",
                    json={"token": venue.token, "nonce": page["nonce"], "q": act, "type": "artist"},
                )
            ).json()
            if not found["items"]:
                continue
            top = found["items"][0]
            plain = top["name"].encode("ascii", "ignore").decode().lower()
            if plain != act.lower().replace("ö", "o"):
                continue
            sel = await guest.post(
                "/v1/public/select",
                json={"token": venue.token, "nonce": page["nonce"], "entity_id": top["entity_id"]},
            )
            if sel.json()["eligible"]:
                ids[crowd].append(top["entity_id"])
    return ids


def plant(
    admin: psycopg.Connection[Any],
    venue: Venue,
    ids: dict[str, list[str]],
    n: int = 90,
    picks: int = 4,
    seed: int = 7,
) -> dict[str, str]:
    """n responses, each four artists from one crowd, in turn. Returns entity id -> crowd."""
    rng = random.Random(seed)
    survey = admin.execute(
        "SELECT id, version FROM survey WHERE business_id = %s AND status = 'published'",
        (venue.business_id,),
    ).fetchone()
    assert survey is not None
    crowd_of: dict[str, str] = {}
    names = list(ids)
    for i in range(n):
        crowd = names[i % len(names)]
        chosen = rng.sample(ids[crowd], picks)
        admin.execute(
            "SELECT public_insert_response(%s, %s, %s, 'v1', NULL, NULL, NULL, 'ok', %s, %s, %s)",
            (
                venue.qr["id"],
                survey[0],
                survey[1],
                chosen,
                ["urn:entity:artist"] * len(chosen),
                uuid.uuid4().bytes,
            ),
        )
        crowd_of.update({e: crowd for e in chosen})
    admin.execute(
        "UPDATE response SET local_weekday = (random() * 6)::int, local_hour = (random() * 23)::int"
    )
    return crowd_of

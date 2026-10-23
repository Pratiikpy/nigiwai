"""The picker and eligibility probe against the real Qloo API, through the whole application. Spends a few dozen
calls of quota, so it only runs with NIGIWAI_RUN_LIVE=1 and a key (NIGIWAI_QLOO_KEY_FILE or QLOO_API_KEY)."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from harness import WorldFactory, make_venue, sign_up

pytestmark = pytest.mark.skipif(
    os.environ.get("NIGIWAI_RUN_LIVE") != "1", reason="set NIGIWAI_RUN_LIVE=1 to spend quota"
)

REALISTIC = [
    ("radiohead", "artist"),
    ("the office", "tv_show"),
    ("blue bottle", "brand"),
    ("normal people", "book"),
    ("zelda", "videogame"),
    ("serial", "podcast"),
    ("parasite", "movie"),
    ("mur", None),  # a short prefix, as typed mid-word
]


async def test_live_picker_search_and_probe(
    make_world: WorldFactory, admin: psycopg.Connection[Any]
) -> None:
    async with make_world(
        with_qloo=False,
        qloo_key_file=os.environ.get("NIGIWAI_QLOO_KEY_FILE"),
        min_completion_seconds=0.0,
    ) as world:
        assert world.app.state.nigiwai.guard is not None, "no Qloo key available"
        owner = await sign_up(world)
        venue = await make_venue(owner)
        guest = world.client()
        page = (await guest.get(f"/v1/public/survey/{venue.token}")).json()
        chosen: list[str] = []
        for query, kind in REALISTIC:
            body: dict[str, Any] = {"token": venue.token, "nonce": page["nonce"], "q": query}
            if kind:
                body["type"] = kind
            r = await guest.post("/v1/public/picker", json=body)
            assert r.status_code == 200, (query, r.text)
            out = r.json()
            print(f"{query!r:16} {out['source']:6} {[i['name'] for i in out['items'][:3]]}")
            assert out["items"], f"no results for {query!r}: {out}"
            if kind and len(chosen) < 5:
                top = out["items"][0]
                assert top["type"] == kind
                sel = await guest.post(
                    "/v1/public/select",
                    json={
                        "token": venue.token,
                        "nonce": page["nonce"],
                        "entity_id": top["entity_id"],
                    },
                )
                assert sel.status_code == 200, sel.text
                print(f"   probe {top['name']!r}: eligible={sel.json()['eligible']}")
                if sel.json()["eligible"] is not False:
                    chosen.append(top["entity_id"])
        assert len(chosen) >= 3
        r = await guest.post(
            "/v1/public/response",
            json={
                "token": venue.token,
                "nonce": page["nonce"],
                "picks": chosen[:5],
                "consent": True,
            },
        )
        assert r.status_code == 201, r.text
        assert admin.execute("SELECT count(*) FROM pick").fetchone() == (len(chosen[:5]),)
        calls = admin.execute(
            "SELECT purpose, endpoint, status, transport FROM qloo_call ORDER BY created_at"
        ).fetchall()
        print(
            f"{len(calls)} Qloo calls; statuses {sorted({c[2] for c in calls})}; transports {sorted({c[3] for c in calls})}"
        )
        assert all(c[2] in ("ok", "empty") for c in calls), calls

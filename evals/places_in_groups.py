"""Do favourite places help or hurt the groups, and does reading them through the allowlist matter?

PRD M3 lets a guest name favourite places. The groups engine (M4) is built from the Qloo tags of what guests pick, and a place carries
tags of a different kind from an act: mostly facilities and descriptions of other people, with taste mixed in. This script measures what
the engine does with place picks, on crowds that are SYNTHETIC in their structure and REAL in their tags:

  * three planted scenes (a quiet, craft one; a loud, casual one; a refined one), each with real acts (read from the saved index of a
    development database that holds real Qloo answers) and real places (searched on Qloo near the same city, by scene-flavoured queries);
  * each respondent belongs to one scene and picks 3 acts and 2 places, 85% of them from their own scene and the rest from anywhere.

It says nothing about whether real guests' place taste forms groups like this. It answers three narrower questions that need no guests:

  1. Does adding two place picks to three act picks change how well the engine recovers the planted scenes (adjusted Rand index) and how
     stable the groups are (bootstrap stability, the measure proofs D and G used)?
  2. Do places alone carry any group signal through the allowlist?
  3. What would reading a place's first ten tags with the artist rule (the blocklist; nothing for a place's facilities) have done?

Usage: uv run python evals/places_in_groups.py --key-file <file with QLOO_API_KEY=...> [--crowds 12] [--respondents 200]
The output is aggregate numbers only, written to evals/out/places_in_groups.json: no item name or tag is saved.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import httpx
import numpy as np
import psycopg
from nigiwai_tribes import Pick, Respondent, Tag, TribesConfig, build_matrix
from nigiwai_tribes.model import assign, fit_nmf
from nigiwai_tribes.stability import ari, bootstrap_stability
from qloo_guard.parse import parse_entity

SCENES = {
    # scene -> (place queries, genre words that mark its acts in the saved index)
    "craft": (
        ["coffee roaster", "bookstore cafe", "bakery", "vinyl record store", "brunch cafe"],
        ["indie", "shoegaze", "dream pop", "folk", "indie folk"],
    ),
    "loud": (
        ["dive bar", "sports bar", "brewery", "pizza", "burger"],
        ["punk", "hardcore", "metal", "garage rock", "hip hop"],
    ),
    "refined": (
        ["cocktail bar", "wine bar", "jazz club", "tasting menu restaurant", "omakase"],
        ["jazz", "soul", "blues", "bossa nova", "classical"],
    ),
}
POINT = "40.7222,-73.9871"
PLACE = "urn:entity:place"
ARTIST = "urn:entity:artist"


def key_from(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*QLOO_API_KEY\s*=\s*(.+)", line)
        if m:
            return m.group(1).strip().strip("\"'")
    raise SystemExit("no QLOO_API_KEY in the key file")


def real_places(key: str) -> dict[str, list[tuple[str, list[Tag], list[Tag]]]]:
    """scene -> places as (id, tags the Guard stores now, the first ten tags as the Guard used to store them)."""
    out: dict[str, list[tuple[str, list[Tag], list[Tag]]]] = {s: [] for s in SCENES}
    with httpx.Client(
        base_url="https://hackathon.api.qloo.com", headers={"X-Api-Key": key}, timeout=30
    ) as client:
        for scene, (queries, _) in SCENES.items():
            seen: set[str] = set()
            for q in queries:
                res = client.get(
                    "/search",
                    params={"query": q, "types": PLACE, "take": "10", "filter.location": POINT},
                )
                res.raise_for_status()
                for raw in res.json().get("results", []):
                    entity = parse_entity(raw)
                    if entity is None or entity.entity_id in seen:
                        continue
                    seen.add(entity.entity_id)
                    kept = [Tag(t.tag_id, t.name, t.type or "") for t in entity.tags]
                    first_ten = [
                        Tag(t["tag_id"], t["name"], t.get("type") or "")
                        for t in (raw.get("tags") or [])[:10]
                        if t.get("tag_id")
                    ]
                    out[scene].append((entity.entity_id, kept, first_ten))
                time.sleep(0.2)
    return out


def real_acts(dsn: str) -> dict[str, list[tuple[str, list[Tag]]]]:
    out: dict[str, list[tuple[str, list[Tag]]]] = {}
    with psycopg.connect(dsn) as conn:
        for scene, (_, words) in SCENES.items():
            rows = conn.execute(
                "SELECT entity_id, tags FROM qloo_entity WHERE type = 'urn:entity:artist' AND tags <> '[]'::jsonb"
                " AND EXISTS (SELECT 1 FROM jsonb_array_elements(tags) t WHERE lower(t->>1) = ANY(%s)) ORDER BY entity_id LIMIT 400",
                (words,),
            ).fetchall()
            out[scene] = [(r[0], [Tag(t[0], t[1], t[2]) for t in r[1]]) for r in rows]
    return out


def draw(
    rng: np.random.Generator,
    picks: list[Pick],
    pool: dict[str, list[tuple[str, list[Tag], list[Tag]]]]
    | dict[str, list[tuple[str, list[Tag]]]],
    scene: int,
    count: int,
    kind: str,
    first_ten: bool,
) -> None:
    """Add `count` picks of one kind: 85% from the respondent's own scene, the rest from any scene."""
    names = list(SCENES)
    for _ in range(count):
        from_scene = names[scene] if rng.random() < 0.85 else names[int(rng.integers(len(names)))]
        items = pool[from_scene]
        item = items[int(rng.integers(len(items)))]
        tags = item[2] if (kind == PLACE and first_ten and len(item) > 2) else item[1]
        if all(p.entity_id != item[0] for p in picks):
            picks.append(Pick(item[0], kind, item[0][:8], tuple(tags)))


def crowd(
    rng: np.random.Generator,
    n: int,
    acts: dict[str, list[tuple[str, list[Tag]]]],
    places: dict[str, list[tuple[str, list[Tag], list[Tag]]]],
    *,
    with_places: bool,
    first_ten: bool,
    with_acts: bool = True,
) -> tuple[list[Respondent], np.ndarray]:
    latent = rng.integers(len(SCENES), size=n)
    people: list[Respondent] = []
    for i, s in enumerate(latent):
        picks: list[Pick] = []
        if with_acts:
            draw(rng, picks, acts, int(s), 3, ARTIST, first_ten)
        if with_places:
            # with acts a respondent names two places (five picks in all); with none, three (the engine wants three usable picks)
            draw(rng, picks, places, int(s), 2 if with_acts else 3, PLACE, first_ten)
        people.append(Respondent(id=f"r{i}", picks=tuple(picks)))
    return people, latent


def measure(
    people: list[Respondent], latent: np.ndarray, cfg: TribesConfig, rng: np.random.Generator
) -> dict[str, float]:
    matrix = build_matrix(people, cfg)
    if matrix.features.shape[0] < 30 or matrix.features.shape[1] < 3:
        return {
            "kept": float(matrix.features.shape[0]),
            "stability": float("nan"),
            "ari": float("nan"),
            "vocab": float(matrix.features.shape[1]),
        }
    kept = {rid: i for i, rid in enumerate(matrix.respondent_ids)}
    truth = np.array([latent[int(r[1:])] for r in matrix.respondent_ids], dtype=np.int64)
    model = fit_nmf(matrix.features, cfg.k, cfg.nmf_max_iter)
    recovered = ari(truth, assign(model, matrix.features))
    stability = bootstrap_stability(matrix.features, cfg.k, cfg, rng)[0]
    return {
        "kept": float(len(kept)),
        "stability": float(stability),
        "ari": float(recovered),
        "vocab": float(matrix.features.shape[1]),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key-file", required=True, type=Path)
    ap.add_argument(
        "--dsn", default="postgresql://nigiwai:nigiwai-dev-only@127.0.0.1:55432/nigiwai"
    )
    ap.add_argument("--crowds", type=int, default=12)
    ap.add_argument("--respondents", type=int, default=200)
    ap.add_argument("--out", type=Path, default=Path("evals/out/places_in_groups.json"))
    args = ap.parse_args()

    places = real_places(key_from(args.key_file))
    acts = real_acts(args.dsn)
    usable = {s: float(np.mean([len(kept) > 0 for _, kept, _ in places[s]])) for s in SCENES}
    sizes = {s: (len(acts[s]), len(places[s])) for s in SCENES}
    print(
        "acts and places per scene:",
        sizes,
        "| share of places with a taste tag:",
        {k: round(v, 2) for k, v in usable.items()},
        flush=True,
    )
    tags_kept = float(np.mean([len(k) for s in SCENES for _, k, _ in places[s]]))
    taste = {
        "genre",
        "category",
        "cuisine",
        "culinary_style",
        "menu_highlight",
        "beverage_offering",
        "specialty_dish",
        "ambience",
        "decor",
        "activity_type",
    }
    tags_old_taste = float(
        np.mean(
            [
                sum(1 for t in first if t.tag_id.split(":")[2] in taste)
                for s in SCENES
                for _, _, first in places[s]
            ]
        )
    )

    cfg = TribesConfig(bootstrap=30, null_runs=1)
    conditions: dict[str, dict[str, bool]] = {
        "acts_only": {"with_places": False, "first_ten": False},
        "acts_and_places_allowlist": {"with_places": True, "first_ten": False},
        "acts_and_places_old_storage_and_blocklist": {"with_places": True, "first_ten": True},
        "places_only_allowlist": {"with_places": True, "first_ten": False, "with_acts": False},
    }
    results: dict[str, list[dict[str, float]]] = {c: [] for c in conditions}
    for crowd_no in range(args.crowds):
        for name, kw in conditions.items():
            rng = np.random.default_rng(
                1000 + crowd_no
            )  # the same planted guests for every condition: only the picks' reading differs
            people, latent = crowd(rng, args.respondents, acts, places, **kw)
            if name == "acts_and_places_old_storage_and_blocklist":
                cfg_c = cfg  # build_matrix reads a place through the allowlist; to emulate the old reading the places are typed as artists
                people = [
                    Respondent(
                        r.id,
                        tuple(
                            Pick(p.entity_id, ARTIST if p.type == PLACE else p.type, p.name, p.tags)
                            for p in r.picks
                        ),
                    )
                    for r in people
                ]
            else:
                cfg_c = cfg
            results[name].append(
                measure(people, latent, cfg_c, np.random.default_rng(7 + crowd_no))
            )
        print(f"crowd {crowd_no + 1}/{args.crowds} done", flush=True)

    summary = {}
    for name, rows in results.items():
        ok = [r for r in rows if not np.isnan(r["ari"])]
        summary[name] = {
            "crowds_measured": len(ok),
            "respondents_kept_mean": round(float(np.mean([r["kept"] for r in rows])), 1),
            "vocabulary_mean": round(float(np.mean([r["vocab"] for r in rows])), 1),
            "recovery_ari_mean": round(float(np.mean([r["ari"] for r in ok])), 3) if ok else None,
            "recovery_ari_sd": round(float(np.std([r["ari"] for r in ok])), 3) if ok else None,
            "stability_mean": round(float(np.mean([r["stability"] for r in ok])), 3)
            if ok
            else None,
            "stability_sd": round(float(np.std([r["stability"] for r in ok])), 3) if ok else None,
        }
    report = {
        "note": "Synthetic crowds with real tags: the planted structure is ours. It tests how the engine reads place picks, not whether real guests' place taste forms groups.",
        "respondents": args.respondents,
        "crowds": args.crowds,
        "places_per_scene": {s: sizes[s][1] for s in SCENES},
        "acts_per_scene": {s: sizes[s][0] for s in SCENES},
        "share_of_places_with_a_taste_tag": usable,
        "mean_taste_tags_kept_per_place_by_the_guard_now": round(tags_kept, 1),
        "mean_taste_tags_in_a_places_first_ten_before": round(tags_old_taste, 1),
        "conditions": summary,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

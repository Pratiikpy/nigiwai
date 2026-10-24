"""Who a group tends to be: a coarse age and gender reading from Qloo's audience data (PRD M7, modelled).

Qloo returns one demographics item per entity, with age bands and a gender split given relative to the average (about
-1 to 1). We never ask guests for age or gender. For each shown group, the group's most-picked items are sent in one call
and the answers are averaged, weighted by how strongly the group picks each item.

What was tested, and what was not (research folder, proofs K and L, 2026-10-23): the gender direction matched
common knowledge for 27 of 27 named brands, artists and shows; a contrast of older against younger age bands put
younger entities below older ones with AUC 0.96 to 0.97 and told 3-item crowds apart 400 of 400 times, but those crowds
came from only 35 and 10 distinct triples, and ground truth was common knowledge rather than a survey. So the reading is
coarse, it is shown as modelled, and its accuracy is NOT VERIFIED.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid4

from qloo_guard import CallContext, DemographicsItem, DemographicsRequest, QlooGuard

log = logging.getLogger("nigiwai.audience")

MIN_ITEMS = 3  # the smallest crowd the age contrast was checked on
OLDER_BANDS = ("45_to_54", "55_and_older")
YOUNGER_BANDS = ("24_and_younger", "25_to_29")
# Midpoint between the young and the older entities' mean contrast in proof L (-0.45). Within CLOSE of it, the reading
# is "mixed ages" rather than a side.
AGE_BOUNDARY = -0.45
AGE_CLOSE = 0.3
GENDER_LEAN = 0.15  # |female index| below this is "no clear lean"; gender values of the tested items ran 0.09 to 0.80

AGE_LABELS = {
    "younger": "Younger-leaning (mostly under 30)",
    "mixed": "Mixed ages",
    "older": "Older-leaning (45 and over)",
}
GENDER_LABELS = {"women": "Leans women", "balanced": "No clear gender lean", "men": "Leans men"}


def age_contrast(item: DemographicsItem) -> float | None:
    """Share of the older bands minus the younger ones, relative to the average audience. None if a band is missing."""
    try:
        return sum(item.age[b] for b in OLDER_BANDS) - sum(item.age[b] for b in YOUNGER_BANDS)
    except KeyError:
        return None


def female_index(item: DemographicsItem) -> float | None:
    if "female" in item.gender and "male" in item.gender:
        return (item.gender["female"] - item.gender["male"]) / 2
    if "female" in item.gender:
        return item.gender["female"]
    if "male" in item.gender:
        return -item.gender["male"]
    return None


def _band_age(x: float) -> str:
    if x < AGE_BOUNDARY - AGE_CLOSE:
        return "younger"
    if x > AGE_BOUNDARY + AGE_CLOSE:
        return "older"
    return "mixed"


def _band_gender(x: float) -> str:
    if x >= GENDER_LEAN:
        return "women"
    if x <= -GENDER_LEAN:
        return "men"
    return "balanced"


def summarise(
    items: Sequence[DemographicsItem], weights: dict[str, float], asked: int
) -> dict[str, Any]:
    """The reading for one group from Qloo's per-item answers. `weights` maps entity id to the group's pick weight."""
    age_sum = gen_sum = w_age = w_gen = 0.0
    used = 0
    for it in items:
        w = max(weights.get(it.entity_id, 0.0), 0.0)
        a, g = age_contrast(it), female_index(it)
        if w <= 0 or a is None or g is None:
            continue
        age_sum += w * a
        gen_sum += w * g
        w_age += w
        w_gen += w
        used += 1
    if used < MIN_ITEMS:
        return {
            "status": "thin",
            "items_asked": asked,
            "items_used": used,
            "reason": (
                f"Qloo has audience data for {used} of this group's {asked} most-picked items; "
                f"at least {MIN_ITEMS} are needed."
            ),
        }
    age = age_sum / w_age
    gender = gen_sum / w_gen
    return {
        "status": "ok",
        "items_asked": asked,
        "items_used": used,
        "age": {
            "index": round(age, 3),
            "band": _band_age(age),
            "label": AGE_LABELS[_band_age(age)],
        },
        "gender": {
            "index": round(gender, 3),
            "band": _band_gender(gender),
            "label": GENDER_LABELS[_band_gender(gender)],
        },
    }


async def read(
    guard: QlooGuard | None, tenant_id: UUID, tribes: Sequence[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """One demographics call per shown group. Returns the readings keyed by the group's index (as a string).

    A failed call leaves that group `unavailable`; it never blocks the groups themselves."""
    out: dict[str, dict[str, Any]] = {}
    if guard is None:
        return out
    for t in tribes:
        if not t.get("shown"):
            continue
        ids = [i["entity_id"] for i in t.get("top_items", []) if i.get("entity_id")]
        weights = {i["entity_id"]: float(i.get("weight", 0.0)) for i in t.get("top_items", [])}
        if len(ids) < MIN_ITEMS:
            continue
        ctx = CallContext(trace_id=uuid4(), purpose="tribes", tenant_id=tenant_id)
        try:
            res = await guard.demographics(DemographicsRequest(signal_entities=tuple(ids)), ctx)
        except Exception:
            log.warning("audience reading failed for group %s", t.get("index"), exc_info=True)
            out[str(t["index"])] = {"status": "unavailable", "reason": "Qloo did not answer."}
            continue
        if res.status in ("ok", "empty", "degraded"):
            out[str(t["index"])] = summarise(res.items, weights, len(ids))
        else:
            out[str(t["index"])] = {"status": "unavailable", "reason": "Qloo did not answer."}
    return out

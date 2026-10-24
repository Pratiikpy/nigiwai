"""The anonymous survey: what a guest's phone talks to. No session, no cookie. The QR token identifies the QR point,
a signed single-use nonce identifies one sitting, and every call is rate limited by hashed address.

Nothing here stores an IP address, user agent or exact timestamp with an answer (ARCHITECTURE 6, 7). Addresses are
hashed with a daily salt, kept only in Redis and gone within a day."""

from __future__ import annotations

import re
import time
import unicodedata
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from ..deps import AppState, State, client_ip_hash
from ..schemas import (
    CardIn,
    DeleteIn,
    DeleteOut,
    PickerIn,
    PickerOut,
    PublicSurveyOut,
    ResponseIn,
    ResponseOut,
    SelectIn,
    SelectOut,
    SurveyQuestions,
    SurveyReward,
)
from ..security import make_nonce, new_token, parse_nonce, token_hash
from ..services import card as card_service
from ..services import share as share_service

router = APIRouter(prefix="/v1/public", tags=["public"])

PICKER_MIN_CHARS = 2
CLOSED = "This survey isn't open right now."
BURST_WINDOW_S = 600.0
BURST_LIMIT = 40  # responses to one QR point in ten minutes before new ones are held for review


class Resolved:
    """What the public_resolve_qr function returns for a valid, active QR point with a published survey."""

    def __init__(self, row: Any, token: str) -> None:
        self.row = row
        self.token = token
        self.qr_hash_hex = token_hash(token).hex()
        self.questions = SurveyQuestions.model_validate(row.questions)

    @property
    def tenant_id(self):  # type: ignore[no-untyped-def]
        return self.row.tenant_id


async def resolve(state: AppState, token: str) -> Resolved:
    async with state.engine.begin() as conn:
        row = (
            await conn.execute(
                text("SELECT * FROM public_resolve_qr(:h)"), {"h": token_hash(token)}
            )
        ).first()
    if row is None:
        raise HTTPException(status_code=404, detail=CLOSED)
    return Resolved(row, token)


async def limit(state: AppState, request: Request, rules: list[tuple[str, int, float]]) -> None:
    ip = client_ip_hash(request, state)
    scoped = [(f"{name}:{ip}", count, window) for name, count, window in rules]
    exceeded = await state.limiter.check_all(scoped)
    if exceeded:
        raise HTTPException(
            status_code=429, detail="Too many requests from this network. Please wait a moment."
        )


async def verify_nonce(state: AppState, resolved: Resolved, nonce: str) -> tuple[str, float]:
    parsed = parse_nonce(state.settings.secret_key, resolved.qr_hash_hex, nonce)
    if parsed is None:
        raise HTTPException(status_code=403, detail="This page has expired. Reload it to continue.")
    nonce_id, expiry = parsed
    issued_at = expiry - state.settings.nonce_ttl_seconds
    return nonce_id, issued_at


# ---- the survey page ------------------------------------------------------------------------------------------
@router.get("/survey/{token}")
async def get_survey(token: str, request: Request, state: State) -> PublicSurveyOut:
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", token):
        raise HTTPException(status_code=404, detail=CLOSED)
    await limit(state, request, [("pub-view", 90, 600.0)])
    resolved = await resolve(state, token)
    row = resolved.row
    return PublicSurveyOut(
        business_name=row.business_name,
        location_name=row.location_name,
        qr_label=row.qr_label,
        questions=resolved.questions,
        reward=SurveyReward.model_validate(row.reward) if row.reward else None,
        consent_text_version=row.consent_text_version,
        consent_body=row.consent_body,
        nonce=make_nonce(
            state.settings.secret_key, resolved.qr_hash_hex, state.settings.nonce_ttl_seconds
        ),
        picker_min_chars=PICKER_MIN_CHARS,
    )


# ---- picker ---------------------------------------------------------------------------------------------------
@router.post("/picker")
async def picker(body: PickerIn, request: Request, state: State) -> PickerOut:
    await limit(state, request, [("pub-pick", 120, 60.0)])
    resolved = await resolve(state, body.token)
    nonce_id, _ = await verify_nonce(state, resolved, body.nonce)
    allowed_types = resolved.questions.picker_types
    types = [body.type] if body.type else list(allowed_types)
    if any(t not in allowed_types for t in types):
        raise HTTPException(status_code=422, detail="That kind of pick is not part of this survey.")
    # Live Qloo searches are capped per sitting; saved matches are not.
    used = await state.redis.incr(f"picker:{nonce_id}")
    if used == 1:
        await state.redis.expire(f"picker:{nonce_id}", state.settings.nonce_ttl_seconds)
    allow_live = used <= state.settings.picker_calls_per_session
    result: PickerOut = await state.picker.search(
        body.q, types, tenant_id=resolved.tenant_id, allow_live=allow_live
    )
    return result


@router.post("/select")
async def select(body: SelectIn, request: Request, state: State) -> SelectOut:
    """The guest chose an item. Qloo is asked once whether its insights accept the item; one it would reject is
    refused here, while the guest can still choose another."""
    await limit(state, request, [("pub-select", 60, 60.0)])
    resolved = await resolve(state, body.token)
    nonce_id, _ = await verify_nonce(state, resolved, body.nonce)
    used = await state.redis.incr(f"select:{nonce_id}")
    if used == 1:
        await state.redis.expire(f"select:{nonce_id}", state.settings.nonce_ttl_seconds)
    if used > 40:
        raise HTTPException(
            status_code=429,
            detail="Too many choices in one sitting. Reload the page to start again.",
        )
    selection = await state.picker.select(body.entity_id, tenant_id=resolved.tenant_id)
    if selection is None:
        raise HTTPException(
            status_code=404, detail="That item was not offered. Search for it again."
        )
    if selection.eligible is False:
        return SelectOut(
            entity_id=body.entity_id,
            eligible=False,
            message="We can't use that one for this survey. Please choose another favourite.",
        )
    return SelectOut(entity_id=body.entity_id, eligible=selection.eligible)


# ---- submit ---------------------------------------------------------------------------------------------------
_DISTRICT_BAD = re.compile(r"[@]|https?:|www\.|\d{5,}|[\x00-\x1f]", re.IGNORECASE)


def clean_district(value: str | None) -> str | None:
    """The district is free text, so it is kept to a short place name: no addresses, emails, links or long numbers."""
    if value is None:
        return None
    normalised = unicodedata.normalize("NFC", value)
    # Control and invisible format characters (newlines, zero-width marks, bidi overrides) are never part of a name.
    if any(unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co") for ch in normalised):
        raise HTTPException(
            status_code=422,
            detail="Please give just the name of your area, for example 'Eastside'.",
        )
    text_value = " ".join(normalised.split())
    if not text_value:
        return None
    if len(text_value) > 60 or _DISTRICT_BAD.search(text_value):
        raise HTTPException(
            status_code=422,
            detail="Please give just the name of your area, for example 'Eastside'.",
        )
    return text_value


@router.post("/response", status_code=201)
async def submit(body: ResponseIn, request: Request, state: State) -> ResponseOut:
    await limit(state, request, [("pub-submit", 60, 3600.0)])
    resolved = await resolve(state, body.token)
    q = resolved.questions
    nonce_id, issued_at = await verify_nonce(state, resolved, body.nonce)

    if not body.consent:
        raise HTTPException(
            status_code=422, detail="Please agree to the consent text to send your answers."
        )
    if body.website:
        # A hidden field a person never sees was filled in: a bot. Answer as if it worked and store nothing.
        return ResponseOut(ok=True, receipt=new_token(16), reward=None)
    if len(set(body.picks)) != len(body.picks):
        raise HTTPException(status_code=422, detail="Each favourite can only be chosen once.")
    if not q.min_picks <= len(body.picks) <= q.max_picks:
        raise HTTPException(
            status_code=422,
            detail=f"Please choose between {q.min_picks} and {q.max_picks} favourites.",
        )
    picks = await state.picker.resolve_picks(body.picks)
    if picks is None:
        raise HTTPException(
            status_code=422,
            detail="One of your picks wasn't recognised. Please search for it again.",
        )
    if any(eligible is False for _, eligible in picks.values()):
        raise HTTPException(
            status_code=422, detail="One of your picks can't be used here. Please choose another."
        )
    allowed = {f"urn:entity:{t}" for t in q.picker_types}
    if any(t not in allowed for t, _ in picks.values()):
        raise HTTPException(
            status_code=422, detail="One of your picks is not a kind this survey asks for."
        )

    age_band = body.age_band if q.ask_age_band else None
    budget = body.budget if q.ask_budget else None
    district = clean_district(body.district) if q.ask_district else None

    # Single use: a nonce submits at most one response.
    if not await state.limiter.consume_nonce(nonce_id, state.settings.nonce_ttl_seconds):
        raise HTTPException(
            status_code=409,
            detail="These answers were already sent. Reload the page to answer again.",
        )

    quality = "ok"
    if (
        time.time() - issued_at < state.settings.min_completion_seconds
        or not await state.limiter.allow(
            f"burst:{resolved.qr_hash_hex}", BURST_LIMIT, BURST_WINDOW_S
        )
    ):
        quality = "quarantined"

    receipt = new_token(16)
    ids = list(body.picks)
    types = [picks[i][0] for i in ids]
    try:
        async with state.engine.begin() as conn:
            await conn.execute(
                text(
                    "SELECT public_insert_response(:qr, :sid, :sv, :cv, :age, :district, CAST(:budget AS smallint),"
                    " :quality, :ids, :types, :dh)"
                ),
                {
                    "qr": resolved.row.qr_point_id,
                    "sid": resolved.row.survey_id,
                    "sv": resolved.row.survey_version,
                    "cv": resolved.row.consent_text_version,
                    "age": age_band,
                    "district": district,
                    "budget": budget,
                    "quality": quality,
                    "ids": ids,
                    "types": types,
                    "dh": token_hash(receipt),
                },
            )
    except DBAPIError as exc:
        await state.redis.delete(f"nonce:{nonce_id}")  # let the guest try again
        if getattr(exc.orig, "sqlstate", None) in (
            "P0002",
            "P0003",
        ):  # the QR was revoked or the survey unpublished meanwhile
            raise HTTPException(status_code=409, detail=CLOSED) from exc
        raise HTTPException(
            status_code=503, detail="We couldn't save your answers. Please try again."
        ) from exc
    return ResponseOut(
        ok=True,
        receipt=receipt,
        reward=SurveyReward.model_validate(resolved.row.reward) if resolved.row.reward else None,
    )


@router.post("/response/delete")
async def delete_response(body: DeleteIn, request: Request, state: State) -> DeleteOut:
    await limit(state, request, [("pub-delete", 20, 3600.0)])
    async with state.engine.begin() as conn:
        removed = (
            await conn.execute(
                text("SELECT public_delete_response(:h)"), {"h": token_hash(body.receipt.strip())}
            )
        ).scalar_one()
    return DeleteOut(removed=bool(removed))


# ---- the Taste Card ---------------------------------------------------------------------------------------------
@router.post("/card")
async def taste_card(body: CardIn, request: Request, state: State) -> dict[str, Any]:
    """The instant card: no Qloo call. Authorised by the guest's receipt alone."""
    await limit(state, request, [("pub-card", 40, 3600.0)])
    ctx = await card_service.load_context(state.engine, body.receipt)
    if ctx is None:
        raise HTTPException(
            status_code=404, detail="We can't find a card for that code. It may have been removed."
        )
    return await card_service.simple_card(state.engine, ctx)


@router.post("/card/extras")
async def taste_card_extras(body: CardIn, request: Request, state: State) -> dict[str, Any]:
    """Related tastes and places near the venue: at most three Qloo calls, skipped when Qloo is slow."""
    await limit(state, request, [("pub-card-extras", 20, 3600.0)])
    ctx = await card_service.load_context(state.engine, body.receipt)
    if ctx is None:
        raise HTTPException(
            status_code=404, detail="We can't find a card for that code. It may have been removed."
        )
    return await card_service.fill_in(state.engine, state.guard, ctx)


@router.post("/card/share")
async def taste_card_share(body: CardIn, request: Request, state: State) -> Response:
    """The shareable image: the venue, the group label and up to three pick names, nothing about the guest."""
    await limit(state, request, [("pub-card-share", 20, 3600.0)])
    ctx = await card_service.load_context(state.engine, body.receipt)
    if ctx is None:
        raise HTTPException(
            status_code=404, detail="We can't find a card for that code. It may have been removed."
        )
    simple = await card_service.simple_card(state.engine, ctx)
    group = simple["group"]
    png = share_service.render_share_card(
        venue=ctx.business_name,
        label=group["label"] if group["status"] == "matched" else None,
        picks=[p["name"] for p in simple["picks"]],
        provisional=bool(group["provisional"]),
    )
    return Response(
        content=png,
        media_type="image/png",
        headers={
            "Content-Disposition": 'attachment; filename="nigiwai-taste-card.png"',
            "X-Alt-Text": share_service.card_alt_text(
                ctx.business_name,
                group["label"] if group["status"] == "matched" else None,
                [p["name"] for p in simple["picks"]],
            )
            .encode("ascii", "replace")
            .decode("ascii"),
        },
    )

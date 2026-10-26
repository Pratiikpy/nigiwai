"""The owner waitlist and the usefulness feedback (PRD M25). Both are written so they can hold nothing about a guest and
nothing that identifies who sent them: the waitlist has an email and the consent text version, the feedback has a yes or no
and an optional line."""

from __future__ import annotations

from typing import Annotated, Literal

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, StringConstraints
from sqlalchemy import text

from ..deps import State, Tenant
from ..schemas import Strict
from .public import limit

public = APIRouter(prefix="/v1/public", tags=["trust"])
owner = APIRouter(prefix="/v1/tenants/{tenant_id}", tags=["trust"])

WAITLIST_VERSION = "waitlist-v2"
WAITLIST_CONSENT = (
    "We keep your email address and the version of this text to tell you about Nigiwai's launch and pricing. "
    "We do not join it to any survey data, and we do not share it. You can ask us to delete it at any time."
)


class WaitlistIn(Strict):
    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=254)]
    consent: bool
    # A field a person never sees: a form filled in by a script fills it, and is quietly ignored.
    website: Annotated[str, StringConstraints(max_length=200)] = ""


class FeedbackIn(Strict):
    kind: Literal["soundcheck", "brief"]
    useful: bool
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=280)] = Field(
        default=""
    )


@public.get("/waitlist/consent")
async def waitlist_consent() -> dict[str, str]:
    return {"version": WAITLIST_VERSION, "body": WAITLIST_CONSENT}


@public.post("/waitlist", status_code=201)
async def join_waitlist(body: WaitlistIn, request: Request, state: State) -> dict[str, bool]:
    """Add an email. A repeat, and a form filled in by a script, both answer exactly as a first sign-up does, so the answer
    tells nobody whether an address was already on the list."""
    await limit(state, request, [("waitlist", 6, 3600.0)])
    if not body.consent:
        raise HTTPException(
            status_code=422, detail="Please agree to the note above to join the waitlist."
        )
    try:
        checked = validate_email(body.email, check_deliverability=False)
    except EmailNotValidError as exc:
        raise HTTPException(
            status_code=422, detail="That doesn't look like an email address."
        ) from exc
    if body.website:
        return {"joined": True}
    async with state.engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO waitlist (email, email_key, consent_version) VALUES (:e, :k, :v)"
                # No conflict target: naming one needs SELECT on the column, and the application role may only insert here.
                " ON CONFLICT DO NOTHING"
            ),
            {"e": checked.normalized, "k": checked.normalized.lower(), "v": WAITLIST_VERSION},
        )
    return {"joined": True}


@owner.post("/feedback", status_code=201)
async def feedback(body: FeedbackIn, state: State, access: Tenant) -> dict[str, bool]:
    """Was a Soundcheck or a brief useful? Stored with no account, venue or person attached."""
    if await state.limiter.check_all([(f"feedback:{access.user_id}", 30, 3600.0)]):
        raise HTTPException(status_code=429, detail="Thank you: that is enough feedback for now.")
    async with state.engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO feedback (kind, useful, note) VALUES (:k, :u, :n)"),
            {"k": body.kind, "u": body.useful, "n": body.note or None},
        )
    return {"stored": True}

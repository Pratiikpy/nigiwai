"""Owner endpoints: businesses, locations, QR points, the survey, and the poster. Every route is tenant-scoped:
the caller must be a member of the tenant in the URL, and the database enforces the same boundary again."""

from __future__ import annotations

import json
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..db import transaction
from ..deps import AppState, State, Tenant, TenantAccess, Writer
from ..schemas import (
    BusinessIn,
    BusinessOut,
    LocationIn,
    LocationOut,
    QrPointIn,
    QrPointOut,
    SurveyIn,
    SurveyOut,
    SurveyQuestions,
    SurveyReward,
)
from ..services import qr
from ..services.poster import render_poster

router = APIRouter(prefix="/v1/tenants/{tenant_id}", tags=["owner"])


def scope(state: AppState, access: TenantAccess):  # type: ignore[no-untyped-def]
    return transaction(state.engine, tenant_id=access.tenant_id, user_id=access.user_id)


async def audit(
    conn: AsyncConnection, access: TenantAccess, action: str, target: str | None = None
) -> None:
    await conn.execute(
        text("INSERT INTO audit_log (tenant_id, actor, action, target) VALUES (:t, :a, :x, :g)"),
        {"t": access.tenant_id, "a": str(access.user_id), "x": action, "g": target},
    )


def not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="not found")


# ---- businesses -----------------------------------------------------------------------------------------------
def _business(row: Any) -> BusinessOut:
    return BusinessOut(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        type=row.type,
        language=row.language,
        currency=row.currency,
    )


@router.get("/businesses")
async def list_businesses(state: State, access: Tenant) -> list[BusinessOut]:
    async with scope(state, access) as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT id, tenant_id, name, type, language, currency FROM business ORDER BY created_at"
                )
            )
        ).all()
    return [_business(r) for r in rows]


@router.post("/businesses", status_code=201)
async def create_business(body: BusinessIn, state: State, access: Writer) -> BusinessOut:
    new_id = uuid4()
    async with scope(state, access) as conn:
        row = (
            await conn.execute(
                text(
                    "INSERT INTO business (id, tenant_id, name, type, language, currency)"
                    " VALUES (:i, :t, :n, :ty, :l, :c)"
                    " RETURNING id, tenant_id, name, type, language, currency"
                ),
                {
                    "i": new_id,
                    "t": access.tenant_id,
                    "n": body.name,
                    "ty": body.type,
                    "l": body.language,
                    "c": body.currency,
                },
            )
        ).one()
        await audit(conn, access, "business.create", str(new_id))
    return _business(row)


@router.put("/businesses/{business_id}")
async def update_business(
    business_id: UUID, body: BusinessIn, state: State, access: Writer
) -> BusinessOut:
    async with scope(state, access) as conn:
        row = (
            await conn.execute(
                text(
                    "UPDATE business SET name = :n, type = :ty, language = :l, currency = :c WHERE id = :i"
                    " RETURNING id, tenant_id, name, type, language, currency"
                ),
                {
                    "i": business_id,
                    "n": body.name,
                    "ty": body.type,
                    "l": body.language,
                    "c": body.currency,
                },
            )
        ).first()
        if row is None:
            raise not_found()
        await audit(conn, access, "business.update", str(business_id))
    return _business(row)


async def _require_business(conn: AsyncConnection, business_id: UUID) -> None:
    if (
        await conn.execute(text("SELECT 1 FROM business WHERE id = :b"), {"b": business_id})
    ).first() is None:
        raise not_found()


# ---- locations ------------------------------------------------------------------------------------------------
_LOCATION_COLUMNS = (
    "id, business_id, name, address, ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon, radius_m, timezone,"
    " price_level, capacity, curfew, excluded_genres, show_nights"
)


def _location(row: Any) -> LocationOut:
    return LocationOut(
        id=row.id,
        business_id=row.business_id,
        name=row.name,
        address=row.address,
        lat=row.lat,
        lon=row.lon,
        radius_m=row.radius_m,
        timezone=row.timezone,
        price_level=row.price_level,
        capacity=row.capacity,
        curfew=row.curfew,
        excluded_genres=list(row.excluded_genres),
        show_nights=[int(n) for n in row.show_nights],
    )


def _location_params(body: LocationIn) -> dict[str, Any]:
    return {
        "n": body.name,
        "a": body.address,
        "lat": body.lat,
        "lon": body.lon,
        "r": body.radius_m,
        "tz": body.timezone,
        "pl": body.price_level,
        "cap": body.capacity,
        "cf": body.curfew,
        "eg": list(body.excluded_genres),
        "sn": list(body.show_nights),
    }


# Longitude first: PostGIS points are (x, y) = (lon, lat), the opposite of how addresses are quoted.
_GEOM = (
    "CASE WHEN CAST(:lon AS float8) IS NULL THEN NULL"
    " ELSE ST_SetSRID(ST_MakePoint(CAST(:lon AS float8), CAST(:lat AS float8)), 4326)::geography END"
)


@router.get("/businesses/{business_id}/locations")
async def list_locations(business_id: UUID, state: State, access: Tenant) -> list[LocationOut]:
    async with scope(state, access) as conn:
        await _require_business(conn, business_id)
        rows = (
            await conn.execute(
                text(
                    f"SELECT {_LOCATION_COLUMNS} FROM location WHERE business_id = :b ORDER BY created_at"
                ),
                {"b": business_id},
            )
        ).all()
    return [_location(r) for r in rows]


@router.post("/businesses/{business_id}/locations", status_code=201)
async def create_location(
    business_id: UUID, body: LocationIn, state: State, access: Writer
) -> LocationOut:
    new_id = uuid4()
    async with scope(state, access) as conn:
        await _require_business(conn, business_id)
        await conn.execute(
            text(
                "INSERT INTO location (id, tenant_id, business_id, name, address, geom, radius_m, timezone,"
                " price_level, capacity, curfew, excluded_genres, show_nights)"
                f" VALUES (:i, :t, :b, :n, :a, {_GEOM}, :r, :tz, :pl, :cap, :cf, :eg, CAST(:sn AS smallint[]))"
            ),
            {**_location_params(body), "i": new_id, "t": access.tenant_id, "b": business_id},
        )
        row = (
            await conn.execute(
                text(f"SELECT {_LOCATION_COLUMNS} FROM location WHERE id = :i"), {"i": new_id}
            )
        ).one()
        await audit(conn, access, "location.create", str(new_id))
    return _location(row)


@router.put("/locations/{location_id}")
async def update_location(
    location_id: UUID, body: LocationIn, state: State, access: Writer
) -> LocationOut:
    async with scope(state, access) as conn:
        result = await conn.execute(
            text(
                f"UPDATE location SET name = :n, address = :a, geom = {_GEOM}, radius_m = :r, timezone = :tz,"
                " price_level = :pl, capacity = :cap, curfew = :cf, excluded_genres = :eg,"
                " show_nights = CAST(:sn AS smallint[]) WHERE id = :i"
            ),
            {**_location_params(body), "i": location_id},
        )
        if result.rowcount == 0:
            raise not_found()
        row = (
            await conn.execute(
                text(f"SELECT {_LOCATION_COLUMNS} FROM location WHERE id = :i"), {"i": location_id}
            )
        ).one()
        await audit(conn, access, "location.update", str(location_id))
    return _location(row)


# ---- QR points ------------------------------------------------------------------------------------------------
def _qr_out(state: AppState, access: TenantAccess, row: Any) -> QrPointOut:
    url = None
    if access.can_write:
        url = qr.survey_url(
            state.settings.public_base_url,
            qr.unseal(state.settings.secret_key, bytes(row.token_enc)),
        )
    return QrPointOut(
        id=row.id,
        location_id=row.location_id,
        label=row.label,
        status=row.status,
        token_hint=row.token_hint,
        created_at=row.created_at,
        url=url,
    )


_QR_COLUMNS = "id, location_id, label, status, token_hint, token_enc, created_at"


@router.get("/locations/{location_id}/qr-points")
async def list_qr_points(location_id: UUID, state: State, access: Tenant) -> list[QrPointOut]:
    async with scope(state, access) as conn:
        rows = (
            await conn.execute(
                text(
                    f"SELECT {_QR_COLUMNS} FROM qr_point WHERE location_id = :l ORDER BY created_at"
                ),
                {"l": location_id},
            )
        ).all()
    return [_qr_out(state, access, r) for r in rows]


@router.post("/locations/{location_id}/qr-points", status_code=201)
async def create_qr_point(
    location_id: UUID, body: QrPointIn, state: State, access: Writer
) -> QrPointOut:
    sealed = qr.mint(state.settings.secret_key)
    new_id = uuid4()
    async with scope(state, access) as conn:
        if (
            await conn.execute(text("SELECT 1 FROM location WHERE id = :l"), {"l": location_id})
        ).first() is None:
            raise not_found()
        await conn.execute(
            text(
                "INSERT INTO qr_point (id, tenant_id, location_id, label, token_hash, token_enc, token_hint)"
                " VALUES (:i, :t, :l, :lb, :h, :e, :hint)"
            ),
            {
                "i": new_id,
                "t": access.tenant_id,
                "l": location_id,
                "lb": body.label,
                "h": sealed.hash,
                "e": sealed.enc,
                "hint": sealed.hint,
            },
        )
        row = (
            await conn.execute(
                text(f"SELECT {_QR_COLUMNS} FROM qr_point WHERE id = :i"), {"i": new_id}
            )
        ).one()
        await audit(conn, access, "qr.create", str(new_id))
    return _qr_out(state, access, row)


@router.post("/qr-points/{qr_point_id}/rotate")
async def rotate_qr_point(qr_point_id: UUID, state: State, access: Writer) -> QrPointOut:
    """A new secret replaces the old one: every printed copy of the old code stops working at once."""
    sealed = qr.mint(state.settings.secret_key)
    async with scope(state, access) as conn:
        result = await conn.execute(
            text(
                "UPDATE qr_point SET token_hash = :h, token_enc = :e, token_hint = :hint, status = 'active',"
                " rotated_at = now() WHERE id = :i"
            ),
            {"h": sealed.hash, "e": sealed.enc, "hint": sealed.hint, "i": qr_point_id},
        )
        if result.rowcount == 0:
            raise not_found()
        row = (
            await conn.execute(
                text(f"SELECT {_QR_COLUMNS} FROM qr_point WHERE id = :i"), {"i": qr_point_id}
            )
        ).one()
        await audit(conn, access, "qr.rotate", str(qr_point_id))
    return _qr_out(state, access, row)


@router.post("/qr-points/{qr_point_id}/revoke")
async def revoke_qr_point(qr_point_id: UUID, state: State, access: Writer) -> QrPointOut:
    async with scope(state, access) as conn:
        result = await conn.execute(
            text("UPDATE qr_point SET status = 'revoked' WHERE id = :i"), {"i": qr_point_id}
        )
        if result.rowcount == 0:
            raise not_found()
        row = (
            await conn.execute(
                text(f"SELECT {_QR_COLUMNS} FROM qr_point WHERE id = :i"), {"i": qr_point_id}
            )
        ).one()
        await audit(conn, access, "qr.revoke", str(qr_point_id))
    return _qr_out(state, access, row)


@router.get("/qr-points/{qr_point_id}/poster.pdf")
async def poster(
    qr_point_id: UUID,
    state: State,
    access: Writer,
    size: Literal["a4", "a6"] = Query(default="a4"),
) -> Response:
    async with scope(state, access) as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT q.status, q.token_enc, q.label, b.name AS business, l.name AS location, b.id AS business_id"
                    " FROM qr_point q JOIN location l ON l.id = q.location_id JOIN business b ON b.id = l.business_id"
                    " WHERE q.id = :i"
                ),
                {"i": qr_point_id},
            )
        ).first()
        if row is None:
            raise not_found()
        if row.status != "active":
            raise HTTPException(
                status_code=409, detail="this QR code is revoked; rotate it to print a new one"
            )
        reward = (
            await conn.execute(
                text(
                    "SELECT reward FROM survey WHERE business_id = :b AND status = 'published'"
                    " ORDER BY created_at DESC, version DESC LIMIT 1"
                ),
                {"b": row.business_id},
            )
        ).scalar_one_or_none()
    url = qr.survey_url(
        state.settings.public_base_url, qr.unseal(state.settings.secret_key, bytes(row.token_enc))
    )
    title = (reward or {}).get("title") if isinstance(reward, dict) else None
    pdf = render_poster(
        business=row.business,
        location=row.label or row.location,
        url=url,
        reward_title=title,
        size=size,
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="nigiwai-poster-{size}.pdf"'},
    )


# ---- survey ---------------------------------------------------------------------------------------------------
def _survey(row: Any) -> SurveyOut:
    return SurveyOut(
        id=row.id,
        version=row.version,
        business_id=row.business_id,
        status=row.status,
        questions=SurveyQuestions.model_validate(row.questions),
        reward=SurveyReward.model_validate(row.reward) if row.reward else None,
        consent_text_version=row.consent_text_version,
    )


_SURVEY_COLUMNS = "id, version, business_id, status, questions, reward, consent_text_version"


@router.get("/businesses/{business_id}/survey")
async def get_survey(business_id: UUID, state: State, access: Tenant) -> SurveyOut | None:
    """The latest saved version, or null when the business has no survey yet (a 200, so a first visit logs no error)."""
    async with scope(state, access) as conn:
        await _require_business(conn, business_id)
        row = (
            await conn.execute(
                text(
                    f"SELECT {_SURVEY_COLUMNS} FROM survey WHERE business_id = :b"
                    " ORDER BY created_at DESC, version DESC LIMIT 1"
                ),
                {"b": business_id},
            )
        ).first()
    return _survey(row) if row is not None else None


@router.put("/businesses/{business_id}/survey")
async def put_survey(business_id: UUID, body: SurveyIn, state: State, access: Writer) -> SurveyOut:
    """Each save is a new version, so a response always points at the exact questions the guest saw. With
    `publish` the new version goes live and any earlier published version is archived."""
    async with scope(state, access) as conn:
        await _require_business(conn, business_id)
        consent = (
            await conn.execute(
                text(
                    "SELECT version FROM consent_text ORDER BY created_at DESC, version DESC LIMIT 1"
                )
            )
        ).scalar_one()
        prior = (
            await conn.execute(
                text("SELECT id, max(version) AS v FROM survey WHERE business_id = :b GROUP BY id"),
                {"b": business_id},
            )
        ).first()
        survey_id = prior.id if prior else uuid4()
        version = (prior.v + 1) if prior else 1
        status = "published" if body.publish else "draft"
        if body.publish:
            await conn.execute(
                text(
                    "UPDATE survey SET status = 'archived' WHERE business_id = :b AND status = 'published'"
                ),
                {"b": business_id},
            )
        await conn.execute(
            text(
                "INSERT INTO survey (id, version, tenant_id, business_id, questions, reward, consent_text_version, status)"
                " VALUES (:i, :v, :t, :b, CAST(:q AS jsonb), CAST(:r AS jsonb), :c, :s)"
            ),
            {
                "i": survey_id,
                "v": version,
                "t": access.tenant_id,
                "b": business_id,
                "q": json.dumps(body.questions.model_dump()),
                "r": json.dumps(body.reward.model_dump()) if body.reward else None,
                "c": consent,
                "s": status,
            },
        )
        row = (
            await conn.execute(
                text(f"SELECT {_SURVEY_COLUMNS} FROM survey WHERE id = :i AND version = :v"),
                {"i": survey_id, "v": version},
            )
        ).one()
        await audit(
            conn,
            access,
            "survey.publish" if body.publish else "survey.save",
            f"{survey_id}@{version}",
        )
    return _survey(row)


# ---- response counts ------------------------------------------------------------------------------------------
@router.get("/businesses/{business_id}/stats")
async def business_stats(business_id: UUID, state: State, access: Tenant) -> dict[str, Any]:
    """Counts only. Anything that describes a group of guests carries the minimum-group rule elsewhere (M16)."""
    async with scope(state, access) as conn:
        await _require_business(conn, business_id)
        totals = (
            await conn.execute(
                text(
                    "SELECT count(*) FILTER (WHERE r.quality_flag = 'ok') AS ok,"
                    "       count(*) FILTER (WHERE r.quality_flag <> 'ok') AS held"
                    " FROM response r JOIN survey s ON s.id = r.survey_id AND s.version = r.survey_version"
                    " WHERE s.business_id = :b"
                ),
                {"b": business_id},
            )
        ).one()
        points = (
            await conn.execute(
                text(
                    "SELECT q.id, q.label, count(r.id) FILTER (WHERE r.quality_flag = 'ok') AS responses"
                    " FROM qr_point q JOIN location l ON l.id = q.location_id"
                    " LEFT JOIN response r ON r.qr_point_id = q.id"
                    " WHERE l.business_id = :b GROUP BY q.id, q.label ORDER BY q.created_at"
                ),
                {"b": business_id},
            )
        ).all()
    return {
        "responses": totals.ok,
        "held_for_review": totals.held,
        "qr_points": [
            {"id": str(p.id), "label": p.label, "responses": p.responses} for p in points
        ],
    }

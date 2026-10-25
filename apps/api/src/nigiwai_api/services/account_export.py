"""A copy of an account's data, for its owner (PRD M14: "data export and deletion for owners").

The file is a ZIP of readable JSON and one CSV, with a README that says what each part is and what is left out on purpose. It holds what the
owner put in (the venue, its places and posters, every version of the survey, the profile and plan, drafts, moves and decisions) and what the
product computed for them (groups, scores, suggestions, answers to their questions, the record of changes). It never holds:

- anything that signs someone in (password and recovery hashes, session tokens) or lets someone in (QR secrets, invitation tokens, receipt hashes);
- an individual guest's answer. The product shows an owner guests only as groups of ten or more, so the copy carries counts and, for items and
  answer values, only those that at least ten guests gave. A copy with one row per guest would let the owner see what the product promises
  guests it never shows;
- Qloo's own call log and raw answers (Qloo's data, not the owner's), or another account's data.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ..db import transaction

MIN_GROUP = 10  # the product's smallest group: an item or an answer value appears only when this many guests gave it

README = """Nigiwai: a copy of your account's data

Account: {account}
Made: {made} by {by}

What is in this file
  account.json         the account, who is in it and their roles, and invitations that are still open (never their links)
  venue.json           your business, its places, QR posters (without their secrets), every version of the survey, the profile and the plan
  guests.json          how many guests answered, when, where, and the items and answers at least {minimum} guests gave
  groups.json          the groups your guests fall into, every version
  scores.json          the acts you checked with Soundcheck, the suggestions made for your crowd, Grow runs and the public-lineup start
  decisions.json       what you accepted or dismissed on Today, moves you logged, and drafts with their status
  questions.json       what you asked Ask Nigiwai and what it answered
  audit_log.csv        the record of changes to the account: what, who, when

What is left out, on purpose
  Passwords, recovery codes, sign-in sessions, QR codes' secrets, invitation links and receipt codes: nothing here can be used to get into
  your account or to remove a guest's answers.
  Individual guests' answers. Nigiwai never shows you a guest on their own, so this copy does not either: it carries counts, and items and
  answer values only when at least {minimum} guests gave them.
  Qloo's own answers and call log. They are Qloo's data, not yours.

Times are UTC. Dates are the venue's own. Every file is plain JSON (or CSV) that any program can read.
"""


def _plain(value: Any) -> Any:
    """What a JSON file can hold: times as ISO text, ids as text, numbers as numbers."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, memoryview)):
        raise TypeError("binary values are never exported")
    raise TypeError(f"cannot export {type(value).__name__}")


def _dump(payload: Any) -> bytes:
    return json.dumps(payload, default=_plain, ensure_ascii=False, indent=2, sort_keys=True).encode(
        "utf-8"
    )


async def _rows(conn: AsyncConnection, sql: str, **params: Any) -> list[dict[str, Any]]:
    return [dict(r._mapping) for r in (await conn.execute(text(sql), params)).all()]


def _suppress(counts: dict[Any, int]) -> dict[str, int]:
    """Only the values at least `MIN_GROUP` guests gave; the rest are left out, not rounded, so a small one cannot be recovered."""
    return {
        str(k): n
        for k, n in sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))
        if n >= MIN_GROUP
    }


async def build(engine: AsyncEngine, tenant_id: UUID, user_id: UUID) -> tuple[bytes, str]:
    """The ZIP and a file name for it. Everything is read inside one transaction as the owner, so row-level security applies as usual."""
    made = datetime.now(UTC)
    async with transaction(engine, tenant_id=tenant_id, user_id=user_id) as conn:
        tenant = (
            await _rows(
                conn, "SELECT id, name, plan, created_at FROM tenant WHERE id = :t", t=tenant_id
            )
        )[0]
        who = {
            str(r["user_id"]): r["email"]
            for r in await _rows(conn, "SELECT user_id, email FROM team_members(:t)", t=tenant_id)
        }
        members = await _rows(
            conn, "SELECT user_id, email, role, joined_at FROM team_members(:t)", t=tenant_id
        )
        invitations = await _rows(
            conn,
            "SELECT id, role, created_at, expires_at, accepted_at, revoked_at FROM invitation WHERE tenant_id = :t ORDER BY created_at",
            t=tenant_id,
        )

        def by(value: Any) -> str | None:
            return who.get(str(value)) if value is not None else None

        businesses = await _rows(
            conn,
            "SELECT id, name, type, language, currency, created_at, atlas_opt_in, atlas_opt_in_at FROM business ORDER BY created_at",
        )
        locations = await _rows(
            conn,
            "SELECT id, business_id, name, address, ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon, hours, price_level, radius_m,"
            " timezone, capacity, curfew, excluded_genres, show_nights, created_at FROM location ORDER BY created_at",
        )
        qr_points = await _rows(
            conn,
            "SELECT id, location_id, label, token_hint, status, created_at, rotated_at FROM qr_point ORDER BY created_at",
        )
        surveys = await _rows(
            conn,
            "SELECT business_id, version, status, questions, reward, consent_text_version, created_at FROM survey ORDER BY business_id, version",
        )
        profiles = await _rows(
            conn,
            "SELECT business_id, version, profile, confirmed_by, confirmed_at FROM business_profile ORDER BY business_id, version",
        )
        plans = await _rows(
            conn,
            "SELECT business_id, version, profile_version, plan, overrides, confirmed_by, confirmed_at FROM dashboard_plan ORDER BY business_id, version",
        )
        for row in profiles + plans:
            row["confirmed_by"] = by(row["confirmed_by"])

        # ---- guests: counts, never rows
        guests: dict[str, Any] = {"minimum_group": MIN_GROUP, "businesses": []}
        for b in businesses:
            base = "FROM response r JOIN qr_point q ON q.id = r.qr_point_id JOIN location l ON l.id = q.location_id WHERE l.business_id = :b"
            totals = (
                await _rows(
                    conn,
                    "SELECT count(*) FILTER (WHERE r.quality_flag = 'ok') AS counted, count(*) FILTER (WHERE r.quality_flag <> 'ok') AS held,"
                    " min(r.local_date) AS first_day, max(r.local_date) AS last_day " + base,
                    b=b["id"],
                )
            )[0]
            by_qr = await _rows(
                conn,
                "SELECT q.label, q.status, count(*) FILTER (WHERE r.quality_flag = 'ok') AS counted FROM qr_point q JOIN location l ON l.id = q.location_id"
                " LEFT JOIN response r ON r.qr_point_id = q.id WHERE l.business_id = :b GROUP BY q.id, q.label, q.status ORDER BY q.label",
                b=b["id"],
            )
            grid = await _rows(
                conn,
                "SELECT r.local_weekday AS weekday, r.local_hour AS hour, count(*) AS scans "
                + base
                + " AND r.quality_flag = 'ok'"
                " GROUP BY 1, 2 ORDER BY 1, 2",
                b=b["id"],
            )
            items = await _rows(
                conn,
                "SELECT p.entity_id, p.entity_type, e.name_nfc AS name, count(DISTINCT p.response_id) AS guests FROM pick p"
                " JOIN response r ON r.id = p.response_id AND r.quality_flag = 'ok' JOIN qr_point q ON q.id = r.qr_point_id"
                " JOIN location l ON l.id = q.location_id LEFT JOIN qloo_entity e ON e.entity_id = p.entity_id"
                " WHERE l.business_id = :b GROUP BY p.entity_id, p.entity_type, e.name_nfc HAVING count(DISTINCT p.response_id) >= :m"
                " ORDER BY guests DESC, name",
                b=b["id"],
                m=MIN_GROUP,
            )
            answers: dict[str, dict[str, int]] = {}
            for column in ("age_band", "district", "budget"):
                found = await _rows(
                    conn,
                    f"SELECT r.{column} AS value, count(*) AS n {base} AND r.quality_flag = 'ok' AND r.{column} IS NOT NULL GROUP BY 1",
                    b=b["id"],
                )
                answers[column] = _suppress({r["value"]: int(r["n"]) for r in found})
            guests["businesses"].append(
                {
                    "business": b["name"],
                    "counted": int(totals["counted"]),
                    "held_for_review": int(totals["held"]),
                    "first_day": totals["first_day"],
                    "last_day": totals["last_day"],
                    "by_poster": [
                        {"poster": r["label"], "status": r["status"], "counted": int(r["counted"])}
                        for r in by_qr
                    ],
                    "scans_by_weekday_and_hour": [
                        {
                            "weekday": int(r["weekday"]),
                            "hour": int(r["hour"]),
                            "scans": int(r["scans"]),
                        }
                        for r in grid
                    ],
                    "items_at_least_minimum_guests": [
                        {
                            "id": r["entity_id"],
                            "type": r["entity_type"],
                            "name": r["name"],
                            "guests": int(r["guests"]),
                        }
                        for r in items
                    ],
                    "answers_at_least_minimum_guests": answers,
                }
            )

        groups = await _rows(
            conn,
            "SELECT business_id, version, state, n, result, created_at FROM tribe_version ORDER BY business_id, version",
        )
        soundchecks = await _rows(
            conn,
            "SELECT business_id, candidate_name, basis_kind, weights_version, result, created_at FROM soundcheck ORDER BY created_at",
        )
        suggestions = await _rows(
            conn,
            "SELECT business_id, status, basis_kind, result, updated_at FROM act_suggestion",
        )
        grow = await _rows(
            conn, "SELECT business_id, status, basis_kind, result, updated_at FROM grow_run"
        )
        lineups = await _rows(
            conn,
            "SELECT business_id, place_name, place_area, status, result, created_at, finished_at FROM lineup_profile",
        )
        decisions = await _rows(
            conn,
            "SELECT business_id, week, action_key, state, decided_by, decided_at FROM board_decision ORDER BY week, action_key",
        )
        moves = await _rows(
            conn,
            "SELECT business_id, kind, title, started_on, ended_on, weekdays, hour_from, hour_to, note, source, created_by, created_at"
            " FROM move ORDER BY started_on",
        )
        drafts = await _rows(
            conn,
            "SELECT business_id, kind, subject, body, status, created_by, created_at, edited_at, decided_by, decided_at FROM draft ORDER BY created_at",
        )
        questions = await _rows(
            conn,
            "SELECT business_id, mode, question, kind, answer, model, created_by, created_at FROM ask_answer ORDER BY created_at",
        )
        audit = await _rows(conn, "SELECT at, actor, action, target FROM audit_log ORDER BY id")
        for row in decisions + moves + drafts + questions:
            for key in ("created_by", "decided_by"):
                if key in row:
                    row[key] = by(row[key])
        for row in audit:
            row["actor"] = who.get(str(row["actor"]), "(someone no longer in the account)")

    stamp = made.strftime("%Y%m%d-%H%M")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "README.txt",
            README.format(
                account=tenant["name"],
                made=made.strftime("%Y-%m-%d %H:%M UTC"),
                by=who.get(str(user_id), "an owner"),
                minimum=MIN_GROUP,
            ),
        )
        z.writestr(
            "account.json",
            _dump(
                {
                    "exported_at": made,
                    "account": {
                        "id": tenant["id"],
                        "name": tenant["name"],
                        "plan": tenant["plan"],
                        "created_at": tenant["created_at"],
                    },
                    "members": [
                        {"email": m["email"], "role": m["role"], "joined_at": m["joined_at"]}
                        for m in members
                    ],
                    "invitations": invitations,
                }
            ),
        )
        z.writestr(
            "venue.json",
            _dump(
                {
                    "businesses": businesses,
                    "places": locations,
                    "posters": qr_points,
                    "survey_versions": surveys,
                    "profile_versions": profiles,
                    "plan_versions": plans,
                }
            ),
        )
        z.writestr("guests.json", _dump(guests))
        z.writestr("groups.json", _dump({"versions": groups}))
        z.writestr(
            "scores.json",
            _dump(
                {
                    "soundchecks": soundchecks,
                    "suggestions": suggestions,
                    "grow": grow,
                    "public_lineups": lineups,
                }
            ),
        )
        z.writestr(
            "decisions.json",
            _dump({"board_decisions": decisions, "moves": moves, "drafts": drafts}),
        )
        z.writestr("questions.json", _dump({"questions": questions}))
        out = io.StringIO(newline="")
        writer = csv.writer(out)
        writer.writerow(["at", "who", "what", "target"])
        for row in audit:
            writer.writerow([row["at"].isoformat(), row["actor"], row["action"], row["target"]])
        z.writestr("audit_log.csv", out.getvalue())
    return buffer.getvalue(), f"nigiwai-export-{stamp}.zip"

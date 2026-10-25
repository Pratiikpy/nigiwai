"""The Booking Brief as a one-page A4 PDF, drawn from the same document the page and the shared link use.

Everything on the page is text from that document (item names, up to three genre labels for each act and our own scores only), so the PDF cannot say anything the
screen does not. Fonts are the poster's embedded Bricolage Grotesque and DM Mono (SIL OFL); a character they cannot draw is
replaced with a question mark and the footer says so, rather than printing an empty box.
"""

from __future__ import annotations

import io
from datetime import date
from typing import Any

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen.canvas import Canvas

from .poster import BRAND, INK, INK_2, PAPER, _drawable, _fonts, _wrap

W, H = A4
M = 44.0
CONTENT = W - 2 * M
RULE = HexColor("#d8ccb3")
SHEET = white
GROUP_COLOURS = [HexColor("#2b4fd0"), HexColor("#e2442a"), HexColor("#0b6f5a")]
SPARE = HexColor("#e8dcc2")
DISPLAY, BODY, MONO = "nigiwai-display", "nigiwai-body", "nigiwai-mono"

LABEL_TEXT = {"measured": "Measured", "observed": "Observed", "modelled": "Modelled"}


class _Ctx:
    def __init__(self, c: Canvas) -> None:
        self.c = c
        self.unprintable = False

    def safe(self, text: str) -> str:
        _fonts()
        out = []
        for ch in text:
            if _drawable(ch, DISPLAY) and _drawable(ch, BODY):
                out.append(ch)
            else:
                out.append("?")
                self.unprintable = True
        return "".join(out)


def _date_words(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%B')}".upper()


def _chip(x: _Ctx, left: float, y: float, kind: str, detail: str | None = None) -> float:
    c = x.c
    label = LABEL_TEXT[kind] + (f" | {x.safe(detail)}" if detail else "")
    size = 6.8
    width = float(pdfmetrics.stringWidth(label, MONO, size)) + 12
    c.saveState()
    c.setLineWidth(0.8)
    if kind == "measured":
        c.setFillColor(INK)
        c.roundRect(left, y - 2.5, width, 12, 6, stroke=0, fill=1)
        c.setFillColor(white)
    else:
        c.setStrokeColor(INK)
        if kind == "modelled":
            c.setDash(2, 1.5)
        c.roundRect(left, y - 2.5, width, 12, 6, stroke=1, fill=0)
        c.setFillColor(INK)
    c.setFont(MONO, size)
    c.drawString(left + 6, y + 1, label)
    c.restoreState()
    return width


def _wrapped(
    x: _Ctx,
    text: str,
    font: str,
    size: float,
    left: float,
    top: float,
    width: float,
    leading: float,
    color: Any = INK,
    max_lines: int | None = None,
) -> float:
    """Draw wrapped text from `top` downwards; return the y below the last line."""
    c = x.c
    c.setFont(font, size)
    c.setFillColor(color)
    lines = _wrap(x.safe(text), font, size, width)
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(".,;") + "…" if _drawable("…", font) else lines[-1]
    y = top
    for line in lines:
        y -= leading
        c.drawString(left, y, line)
    return y


def render(doc: dict[str, Any]) -> bytes:
    _fonts()
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=A4, pageCompression=1)
    c.setTitle(f"Booking Brief: {doc['venue']['business']}")
    c.setAuthor("Nigiwai")
    c.setSubject("Who to book next, for the crowd you actually have")
    x = _Ctx(c)

    c.setFillColor(PAPER)
    c.rect(0, 0, W, H, stroke=0, fill=1)
    c.setFillColor(SHEET)
    c.rect(M - 14, 30, CONTENT + 28, H - 60, stroke=0, fill=1)

    y = H - 56
    # Eyebrow.
    c.setFillColor(BRAND)
    c.rect(M, y - 1, 5, 5, stroke=0, fill=1)
    eyebrow = f"BOOKING BRIEF  ·  {doc['venue']['business'].upper()}  ·  {_date_words(doc['date'])}"
    c.setFillColor(INK_2)
    c.setFont(MONO, 7.5)
    c.drawString(M + 11, y, x.safe(eyebrow))
    y -= 8
    y = _wrapped(x, doc["title"], DISPLAY, 24, M, y, CONTENT, 26, INK)
    y -= 10
    c.setStrokeColor(INK)
    c.setLineWidth(1.6)
    c.line(M, y, M + CONTENT, y)
    y -= 6

    if doc["status"] != "ok":
        c.setFont(DISPLAY, 15)
        c.setFillColor(INK)
        y -= 30
        c.drawString(M, y, "Not enough data yet")
        y = _wrapped(x, doc["reason"], BODY, 10.5, M, y - 4, CONTENT, 14, INK_2)
        _footer(x, doc, y_floor=60)
        c.showPage()
        c.save()
        return buf.getvalue()

    # Your crowd.
    basis = doc["basis"]
    y -= 20
    c.setFont(DISPLAY, 14)
    c.setFillColor(INK)
    c.drawString(M, y, "Your crowd")
    y -= 12
    left = M
    for i, g in enumerate(doc["groups"]):
        wpx = CONTENT * g["share"] / 100
        c.setFillColor(GROUP_COLOURS[i % 3])
        c.rect(left, y - 8, wpx, 9, stroke=0, fill=1)
        left += wpx
    if left < M + CONTENT - 0.5:
        c.setFillColor(SPARE)
        c.rect(left, y - 8, M + CONTENT - left, 9, stroke=0, fill=1)
    y -= 22
    cols = (M, M + 168, M + 262)
    c.setFont(BODY, 7.8)
    c.setFillColor(INK_2)
    for xx, head in zip(
        cols,
        ("Group", "Guests" if basis["unit"] == "guests" else "Acts", "When they come"),
        strict=True,
    ):
        c.drawString(xx, y, head)
    y -= 5
    c.setStrokeColor(RULE)
    c.setLineWidth(0.7)
    c.line(M, y, M + CONTENT, y)
    for i, g in enumerate(doc["groups"]):
        top = y - 3
        c.setFillColor(GROUP_COLOURS[i % 3])
        c.circle(cols[0] + 3, top - 7.5, 2.6, stroke=0, fill=1)
        # A group's name can be as long as three tags: it wraps inside its own column instead of running into the next one.
        label_bottom = _wrapped(
            x,
            g["label"],
            BODY,
            9.5,
            cols[0] + 11,
            top,
            cols[1] - cols[0] - 17,
            10.5,
            INK,
            max_lines=2,
        )
        count = f"{g['size']} of {basis['n']}" if basis["unit"] == "guests" else f"{g['size']} acts"
        c.setFont(BODY, 9.5)
        c.drawString(cols[1], top - 10, count)
        when = g["when"] or ("Not enough scans yet to say" if basis["unit"] == "guests" else "")
        bottom = _wrapped(
            x, when, BODY, 8.5, cols[2], top - 1.5, M + CONTENT - cols[2], 10.5, INK_2, max_lines=2
        )
        y = min(top - 17, bottom - 5, label_bottom - 5)
        c.setStrokeColor(RULE)
        c.line(M, y, M + CONTENT, y)
    y -= 12
    cx = M
    cx += _chip(x, cx, y, "measured", f"n = {basis['n']}") + 5
    cx += _chip(x, cx, y, "modelled", "groups") + 6
    note = doc["notes"][0] if doc["notes"] else ""
    _wrapped(x, note, BODY, 7.6, cx, y + 9, M + CONTENT - cx, 9.5, INK_2, max_lines=2)

    # Acts.
    y -= 30
    c.setFont(DISPLAY, 14)
    c.setFillColor(INK)
    c.drawString(M, y, "Three acts to consider" if len(doc["acts"]) == 3 else "Acts to consider")
    y -= 16
    acol = (M, M + 168, M + 262, M + 384)
    c.setFont(BODY, 7.8)
    c.setFillColor(INK_2)
    for xx, head in zip(acol, ("Act", "Soundcheck", "Best for", "Watch out for"), strict=True):
        c.drawString(xx, y, head)
    y -= 5
    c.setStrokeColor(RULE)
    c.line(M, y, M + CONTENT, y)
    for a in doc["acts"]:
        top = y - 4
        c.setFont(DISPLAY, 11)
        c.setFillColor(INK)
        name_bottom = _wrapped(
            x,
            a["name"],
            DISPLAY,
            11,
            acol[0],
            top + 1,
            acol[1] - acol[0] - 10,
            12,
            INK,
            max_lines=2,
        )
        genres = ", ".join(a["genres"])
        if genres:
            name_bottom = _wrapped(
                x,
                genres,
                BODY,
                7.6,
                acol[0],
                name_bottom - 1,
                acol[1] - acol[0] - 10,
                9,
                INK_2,
                max_lines=1,
            )
        c.setFont(DISPLAY, 18)
        c.setFillColor(INK)
        c.drawString(acol[1], top - 15, str(a["score"]))
        c.setFont(BODY, 7.6)
        c.setFillColor(INK_2)
        c.drawString(acol[1], top - 26, f"range {a['band'][0]} to {a['band'][1]}")
        b1 = _wrapped(
            x,
            a["best_for"] or "",
            BODY,
            8.6,
            acol[2],
            top + 1,
            acol[3] - acol[2] - 10,
            10.5,
            INK,
            max_lines=3,
        )
        b2 = _wrapped(
            x,
            a["watch"] or "Nothing stands out.",
            BODY,
            8.6,
            acol[3],
            top + 1,
            M + CONTENT - acol[3],
            10.5,
            INK,
            max_lines=4,
        )
        y = min(name_bottom, b1, b2, top - 30) - 3
        fits = " · ".join(f"{g['label']} {g['fit']}" for g in a["groups"])
        if fits:
            y = (
                _wrapped(
                    x,
                    "Fit by group: " + fits,
                    BODY,
                    7.2,
                    acol[0],
                    y,
                    CONTENT,
                    9,
                    INK_2,
                    max_lines=2,
                )
                - 3
            )
        y -= 3
        c.setStrokeColor(RULE)
        c.line(M, y, M + CONTENT, y)

    # Wildcard and nights.
    y -= 24
    half = CONTENT / 2 - 10
    c.setFont(DISPLAY, 14)
    c.setFillColor(INK)
    c.drawString(M, y, "This month's Wildcard")
    c.drawString(M + half + 20, y, "Best nights")
    w = doc["wildcard"]
    top = y - 3
    if w:
        wb = _wrapped(
            x,
            f"{w['name']} ({', '.join(w['genres'])}). Soundcheck {w['score']}, range {w['band'][0]} to {w['band'][1]}. "
            "A small act that ranks well for your two biggest groups.",
            BODY,
            9.2,
            M,
            top,
            half,
            12.5,
            INK,
            max_lines=5,
        )
    else:
        wb = _wrapped(
            x,
            "No small act ranked well for both of your biggest groups this time.",
            BODY,
            9.2,
            M,
            top,
            half,
            12.5,
            INK_2,
            max_lines=3,
        )
    nb = _wrapped(
        x,
        doc["nights"]["text"] if doc["nights"] else "No night stands out for these acts.",
        BODY,
        9.2,
        M + half + 20,
        top,
        half,
        12.5,
        INK,
        max_lines=4,
    )
    cx = M
    cy = min(wb, nb) - 14
    cx += _chip(x, cx, cy, "modelled") + 4
    _chip(x, M + half + 20, cy, "modelled")
    y = cy - 8

    _footer(x, doc, y_floor=y)
    c.showPage()
    c.save()
    return buf.getvalue()


def _footer(x: _Ctx, doc: dict[str, Any], y_floor: float) -> None:
    c = x.c
    y = 118.0
    c.setStrokeColor(INK)
    c.setLineWidth(1.6)
    c.line(M, y, M + CONTENT, y)
    y -= 4
    how = doc["how"] or "Scores come from the app, where every figure shows its working."
    y = _wrapped(
        x, "How this was computed. " + how, BODY, 7.4, M, y, CONTENT, 9.2, INK_2, max_lines=5
    )
    extra = [n for n in doc["notes"][1:]]
    for n in extra[:2]:
        y = _wrapped(x, n, BODY, 7.4, M, y - 1, CONTENT, 9.2, INK_2, max_lines=2)
    tail = (
        "Taste data from Qloo. This brief holds item names, genre labels and our own scores only."
    )
    if x.unprintable:
        tail += " Some characters in names could not be printed here and show as ?; the online brief shows them."
    _wrapped(x, tail, BODY, 7.4, M, y - 1, CONTENT, 9.2, INK_2, max_lines=3)

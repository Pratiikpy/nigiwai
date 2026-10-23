"""The printable QR poster (A4 and A6 table card), drawn as vector PDF with the design system's Riso Counter colours.

The QR is drawn from its module matrix, not rasterised, so it stays sharp at any print size. Error correction is
level Q so a coffee ring or a scuffed corner still scans. Fonts are embedded TrueType (SIL OFL, see assets/fonts).
"""

from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path
from typing import Literal

import qrcode
from qrcode.constants import ERROR_CORRECT_Q
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, A6
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
PAPER = HexColor("#f3eada")
INK = HexColor("#1b2030")
INK_2 = HexColor("#454b5c")
BRAND = HexColor("#f05a38")
HIGHLIGHT = HexColor("#f4c542")
SURFACE = HexColor("#fffaef")

Size = Literal["a4", "a6"]


@lru_cache(maxsize=1)
def _fonts() -> dict[str, set[int]]:
    """Register the fonts once; return each font's supported code points so a name the font cannot draw is detected."""
    coverage: dict[str, set[int]] = {}
    for key, file in (
        ("display", "BricolageGrotesque-ExtraBold.ttf"),
        ("body", "BricolageGrotesque-Medium.ttf"),
        ("mono", "DMMono-Medium.ttf"),
    ):
        font = TTFont(f"nigiwai-{key}", str(FONTS / file))
        pdfmetrics.registerFont(font)
        coverage[f"nigiwai-{key}"] = set(font.face.charToGlyph)
    return coverage


def _drawable(text: str, font: str) -> bool:
    cov = _fonts()[font]
    return all(ord(c) in cov or c.isspace() for c in text)


def _fit(text: str, font: str, max_width: float, start: float, floor: float) -> float:
    size = start
    while size > floor and pdfmetrics.stringWidth(text, font, size) > max_width:
        size -= 1
    return size


def _wrap(text: str, font: str, size: float, max_width: float) -> list[str]:
    lines: list[str] = []
    line = ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if pdfmetrics.stringWidth(trial, font, size) <= max_width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _qr_matrix(url: str) -> list[list[bool]]:
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_Q, border=0, box_size=1)
    qr.add_data(url)
    qr.make(fit=True)
    return [[bool(cell) for cell in row] for row in qr.get_matrix()]


def render_poster(
    *, business: str, location: str, url: str, reward_title: str | None = None, size: Size = "a4"
) -> bytes:
    _fonts()
    page = A4 if size == "a4" else A6
    w, h = page
    k = w / A4[0]  # scale every measurement from the A4 layout
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=page, pageCompression=1)
    c.setTitle("Nigiwai survey poster")
    c.setAuthor("Nigiwai")

    c.setFillColor(PAPER)
    c.rect(0, 0, w, h, stroke=0, fill=1)

    margin = 44 * k
    inner = w - 2 * margin

    # Header: the business, then the ask.
    name = business.strip()
    header_font = "nigiwai-display" if _drawable(name, "nigiwai-display") else None
    y = h - margin - 14 * k
    c.setFillColor(INK_2)
    c.setFont("nigiwai-mono", 11 * k)
    c.drawString(margin, y, "NIGIWAI  /  TASTE SURVEY")
    y -= 40 * k
    if header_font:
        size_pt = _fit(name, header_font, inner, 40 * k, 20 * k)
        c.setFillColor(INK)
        c.setFont(header_font, size_pt)
        c.drawString(margin, y, name)
        y -= size_pt * 0.4
    y -= 34 * k
    c.setFillColor(INK)
    headline = "Tell us what you love."
    c.setFont("nigiwai-display", _fit(headline, "nigiwai-display", inner, 52 * k, 24 * k))
    c.drawString(margin, y, headline)
    y -= 30 * k
    c.setFillColor(INK_2)
    sub = "A few favourites. Under a minute. No name, no email."
    c.setFont("nigiwai-body", _fit(sub, "nigiwai-body", inner, 17 * k, 9 * k))
    c.drawString(margin, y, sub)

    # The QR card, with a hard offset shadow in the Riso style.
    matrix = _qr_matrix(url)
    n = len(matrix)
    qr_side = min(inner - 36 * k, 340 * k)
    module = qr_side / n
    pad = 18 * k
    card = qr_side + 2 * pad
    card_x = (w - card) / 2
    card_y = y - 36 * k - card
    c.setFillColor(INK)
    c.rect(card_x + 7 * k, card_y - 7 * k, card, card, stroke=0, fill=1)
    c.setFillColor(SURFACE)
    c.setStrokeColor(INK)
    c.setLineWidth(2.2 * k)
    c.rect(card_x, card_y, card, card, stroke=1, fill=1)
    c.setFillColor(INK)
    qx, qy = card_x + pad, card_y + pad
    for row_index, row in enumerate(matrix):
        for col_index, dark in enumerate(row):
            if dark:
                # A hair of overlap hides seams between modules in some PDF viewers.
                c.rect(
                    qx + col_index * module,
                    qy + (n - 1 - row_index) * module,
                    module + 0.15,
                    module + 0.15,
                    stroke=0,
                    fill=1,
                )

    # Under the card: how to scan, the written address, and the reward when there is one.
    y = card_y - 34 * k
    c.setFillColor(INK)
    c.setFont("nigiwai-display", 22 * k)
    c.drawCentredString(w / 2, y, "Point your phone camera here")
    y -= 24 * k
    c.setFillColor(INK_2)
    c.setFont("nigiwai-mono", _fit(url, "nigiwai-mono", inner, 11 * k, 6 * k))
    c.drawCentredString(w / 2, y, url)
    if reward_title and _drawable(reward_title, "nigiwai-display"):
        y -= 40 * k
        label_size = 15 * k
        c.setFont("nigiwai-display", label_size)
        text_w = pdfmetrics.stringWidth(reward_title, "nigiwai-display", label_size)
        box_w = min(text_w + 36 * k, inner)
        box_h = 34 * k
        c.setFillColor(HIGHLIGHT)
        c.setStrokeColor(INK)
        c.setLineWidth(1.6 * k)
        c.rect((w - box_w) / 2, y - 11 * k, box_w, box_h, stroke=1, fill=1)
        c.setFillColor(INK)
        c.drawCentredString(w / 2, y, reward_title[:80])

    # Footer: what the guest should know, in the order they would ask.
    c.setStrokeColor(INK)
    c.setLineWidth(1 * k)
    foot_y = margin + 58 * k
    c.line(margin, foot_y, w - margin, foot_y)
    c.setFillColor(INK_2)
    note = (
        "Your answers are anonymous: we keep no name, email, IP address or exact time. "
        "You get a receipt code to delete your answers any time."
    )
    note_size = 9.5 * k
    c.setFont("nigiwai-body", note_size)
    ty = foot_y - 16 * k
    for line in _wrap(note, "nigiwai-body", note_size, inner):
        c.drawString(margin, ty, line)
        ty -= 13 * k
    where = location.strip()[:80].upper()
    if where and _drawable(where, "nigiwai-mono"):
        c.setFont("nigiwai-mono", 8.5 * k)
        c.drawString(margin, margin - 4 * k, where)

    c.showPage()
    c.save()
    return buf.getvalue()

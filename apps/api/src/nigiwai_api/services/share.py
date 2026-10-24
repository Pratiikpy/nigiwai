"""The shareable Taste Card image: names only.

It carries the venue's name, the group label and up to three picks as text. No guest name, photo, location, receipt or
Qloo image is on it (showing Qloo's images on a shared card has not been checked against its terms). Rendered on the
server from the design system's colours and the same TrueType fonts as the poster.
"""

from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
PAPER = (243, 234, 218)
INK = (27, 32, 48)
INK_2 = (69, 75, 92)
BRAND = (240, 90, 56)
HIGHLIGHT = (244, 197, 66)
SURFACE = (255, 250, 239)
W, H = 1080, 1350
MARGIN = 72


@lru_cache(maxsize=16)
def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


@lru_cache(maxsize=8)
def _cmap(name: str) -> frozenset[int]:
    from fontTools.ttLib import TTFont

    return frozenset(TTFont(str(FONTS / name)).getBestCmap())


def _covers(name: str, text: str) -> bool:
    """Whether the font file has a glyph for every character (a missing one would draw as an empty box)."""
    cmap = _cmap(name)
    return bool(text.strip()) and all(ord(ch) in cmap or ch.isspace() for ch in text)


def _wrap(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int
) -> list[str]:
    lines: list[str] = []
    line = ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def render_share_card(
    *, venue: str, label: str | None, picks: list[str], provisional: bool
) -> bytes:
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    display = "BricolageGrotesque-ExtraBold.ttf"
    body = "BricolageGrotesque-Medium.ttf"
    mono = "DMMono-Medium.ttf"

    d.text((MARGIN, MARGIN), "NIGIWAI  /  TASTE CARD", font=_font(mono, 30), fill=INK_2)
    name = venue.strip()
    f_venue = _font(display, 56)
    if _covers(display, name):
        d.text((MARGIN, MARGIN + 70), name, font=f_venue, fill=INK)

    # The group, on the brand colour with a hard offset shadow (Direction A).
    x0, y0, x1, y1 = MARGIN, 300, W - MARGIN, 760
    d.rectangle((x0 + 14, y0 + 14, x1 + 14, y1 + 14), fill=INK)
    d.rectangle((x0, y0, x1, y1), fill=BRAND, outline=INK, width=5)
    d.text(
        (x0 + 48, y0 + 44),
        "People who picked similar things here also pick",
        font=_font(body, 34),
        fill=INK,
    )
    title = label if label and _covers(display, label) else "A crowd still forming"
    f_title = _font(display, 118 if len(title) < 14 else 92)
    ty: float = y0 + 130
    for line in _wrap(d, title, f_title, x1 - x0 - 96)[:3]:
        d.text((x0 + 48, ty), line, font=f_title, fill=INK)
        ty += f_title.size + 6
    if provisional and label:
        d.rounded_rectangle(
            (x0 + 48, y1 - 96, x0 + 48 + 330, y1 - 40),
            radius=28,
            fill=SURFACE,
            outline=INK,
            width=3,
        )
        d.text((x0 + 48 + 28, y1 - 87), "Early read", font=_font(mono, 30), fill=INK)

    d.text((MARGIN, 820), "THREE PICKS", font=_font(mono, 30), fill=INK_2)
    f_pick = _font(display, 52)
    y = 880
    shown = 0
    for p in picks:
        if shown == 3:
            break
        if not _covers(display, p):
            continue
        lines = _wrap(d, p, f_pick, W - 2 * MARGIN - 90)[:2]
        d.ellipse((MARGIN, y + 18, MARGIN + 28, y + 46), fill=HIGHLIGHT, outline=INK, width=3)
        for line in lines:
            d.text((MARGIN + 60, y), line, font=f_pick, fill=INK)
            y += 62
        y += 24
        shown += 1

    d.line((MARGIN, H - 150, W - MARGIN, H - 150), fill=INK, width=3)
    note = "This card shows what people with similar picks tend to like. It says nothing about any one person."
    for i, line in enumerate(_wrap(d, note, _font(body, 28), W - 2 * MARGIN)[:2]):
        d.text((MARGIN, H - 126 + i * 36), line, font=_font(body, 28), fill=INK_2)

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def card_alt_text(venue: str, label: str | None, picks: list[str]) -> str:
    parts: list[Any] = [f"Taste Card for {venue}"]
    if label:
        parts.append(f"group {label}")
    if picks:
        parts.append("picks: " + ", ".join(picks[:3]))
    return ". ".join(str(p) for p in parts)

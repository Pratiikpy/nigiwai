"""Build the static TrueType fonts the QR poster needs from the design system's variable WOFF2 files.

reportlab embeds TrueType only, and the design system ships variable WOFF2. This instances Bricolage Grotesque at
the two weights the poster uses and converts DM Mono. Both are SIL Open Font License 1.1. Run once; the output is
committed under apps/api/src/nigiwai_api/assets/fonts. Usage: uv run python tools/build_poster_fonts.py <design-fonts-dir>
"""

from __future__ import annotations

import sys
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

OUT = Path(__file__).resolve().parents[1] / "apps/api/src/nigiwai_api/assets/fonts"


def to_ttf(font: TTFont, name: str) -> None:
    font.flavor = None
    font.save(OUT / name)
    print("wrote", name)


def main(src: Path) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for weight, label in ((800, "ExtraBold"), (500, "Medium")):
        font = TTFont(src / "bricolage-normal-300-800.woff2")
        axes = {a.axisTag: a for a in font["fvar"].axes}
        limits = {"wght": weight}
        if "wdth" in axes:
            limits["wdth"] = 100
        if "opsz" in axes:
            limits["opsz"] = 24
        inst = instancer.instantiateVariableFont(font, limits)
        to_ttf(inst, f"BricolageGrotesque-{label}.ttf")
    to_ttf(TTFont(src / "dmmono-normal-500.woff2"), "DMMono-Medium.ttf")


if __name__ == "__main__":
    main(Path(sys.argv[1]))

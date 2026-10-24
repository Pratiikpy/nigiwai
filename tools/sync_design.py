"""Copy the design system's CSS and the fonts Direction A uses into the web app.

The design system lives in the research folder (design/). The web app owns its copy so it builds from a clean
checkout. Usage: uv run python tools/sync_design.py <path-to-design-dir> [css-file ...]
Direction A ("Riso Counter") is the shipped direction (docs/DECISIONS.md D11), so only its two font families are
copied; the other directions' tokens stay in tokens.css because the files are shared verbatim.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS_OUT = ROOT / "apps/web/src/design"
FONT_OUT = ROOT / "apps/web/public/fonts"
DEFAULT_CSS = [
    "tokens.css",
    "base.css",
    "components.css",
    "directions.css",
    "survey.css",
    "trace.css",
    "map.css",
    "v06.css",
]
FONTS = ["bricolage-normal-300-800.woff2", "dmmono-normal-400.woff2", "dmmono-normal-500.woff2"]

FONTS_CSS = """/* Direction A fonts, self-hosted (SIL Open Font License 1.1; see NOTICE.md). Latin subset. */
@font-face {
  font-family: 'Bricolage Grotesque';
  font-style: normal;
  font-weight: 300 800;
  font-stretch: 100%;
  font-display: swap;
  src: url('/fonts/bricolage-normal-300-800.woff2') format('woff2');
}
@font-face {
  font-family: 'DM Mono';
  font-style: normal;
  font-weight: 400;
  font-display: swap;
  src: url('/fonts/dmmono-normal-400.woff2') format('woff2');
}
@font-face {
  font-family: 'DM Mono';
  font-style: normal;
  font-weight: 500;
  font-display: swap;
  src: url('/fonts/dmmono-normal-500.woff2') format('woff2');
}
"""


def main(design: Path, css: list[str]) -> None:
    CSS_OUT.mkdir(parents=True, exist_ok=True)
    FONT_OUT.mkdir(parents=True, exist_ok=True)
    for name in css or DEFAULT_CSS:
        shutil.copyfile(design / "assets/css" / name, CSS_OUT / name)
        print("css", name)
    (CSS_OUT / "fonts.css").write_text(FONTS_CSS, encoding="utf-8", newline="\n")
    for name in FONTS:
        shutil.copyfile(design / "assets/fonts" / name, FONT_OUT / name)
        print("font", name)


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2:])

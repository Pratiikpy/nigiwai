"""Save a Booking Brief for each demo venue as a PDF and a PNG preview in docs/samples.

The briefs are fetched from a running API's public demo routes (`just dev-api`, with the demo venues built by `just demo`), so a
sample is exactly what a visitor downloads: the real document, not a mock-up. Each holds item names, up to three genre labels for
each act and our own scores, and is labelled as modelled from public lineups. Usage: uv run python tools/sample_briefs.py [api-url]
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pypdfium2 as pdfium

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "samples"
SLUGS = ("mercury-lounge", "the-hideout", "empty-bottle")
PREVIEW_SCALE = 1.6  # pixels per PDF point: sharp enough to read, small enough for a README


def main(api: str) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=api.rstrip("/"), timeout=60.0) as client:
        for slug in SLUGS:
            res = client.get(f"/v1/public/demo/{slug}/brief.pdf")
            if res.status_code != 200 or not res.content.startswith(b"%PDF"):
                print(
                    f"{slug}: the API answered {res.status_code}; is the venue built (`just demo`)?",
                    file=sys.stderr,
                )
                return 1
            pdf_path = OUT / f"booking-brief-{slug}.pdf"
            pdf_path.write_bytes(res.content)
            page = pdfium.PdfDocument(str(pdf_path))[0]
            page.render(scale=PREVIEW_SCALE).to_pil().save(
                OUT / f"booking-brief-{slug}.png", optimize=True
            )
            print(f"{slug}: {pdf_path.relative_to(ROOT)} and its preview written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"))

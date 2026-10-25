"""The sample Booking Briefs `just samples` saves to docs/samples (PRD M25): real PDFs, one page each, labelled as modelled, holding no
identifiers, each with a preview image. The folder is not committed (docs/HUMAN.md H8), so these run where it has been made."""

from __future__ import annotations

import re
from pathlib import Path

import pypdfium2 as pdfium
import pytest

ROOT = Path(__file__).resolve().parents[3]
SAMPLES = ROOT / "docs" / "samples"
pytestmark = pytest.mark.skipif(
    not SAMPLES.is_dir(),
    reason="docs/samples is made locally by `just samples`; it is not committed (docs/HUMAN.md H8)",
)
VENUES = {
    "mercury-lounge": "MERCURY LOUNGE",
    "the-hideout": "THE HIDEOUT",
    "empty-bottle": "EMPTY BOTTLE",
}


@pytest.mark.parametrize(("slug", "name"), VENUES.items())
def test_a_sample_brief_is_the_real_one_page_document_for_its_venue(slug: str, name: str) -> None:
    pdf = pdfium.PdfDocument(str(SAMPLES / f"booking-brief-{slug}.pdf"))
    assert len(pdf) == 1
    text = " ".join(pdf[0].get_textpage().get_text_range().split())
    assert "BOOKING BRIEF" in text.upper() and name in text.upper()
    assert "Three acts to consider" in text and "Soundcheck" in text
    # it says where the crowd comes from, and how the numbers were made
    assert (
        "Modelled from public lineups (MusicBrainz, public domain), not from your own guests"
        in text
    )
    assert "How this was computed" in text
    assert "This brief holds item names, genre labels and our own scores only." in text
    # nothing that identifies a venue's records or Qloo's: no id of any kind
    assert not re.search(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text, re.I
    )
    assert "popularity" not in text.lower() and "affinity" not in text.lower()


@pytest.mark.parametrize("slug", VENUES)
def test_a_sample_has_a_preview_image(slug: str) -> None:
    preview = SAMPLES / f"booking-brief-{slug}.png"
    assert preview.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" and preview.stat().st_size > 20_000

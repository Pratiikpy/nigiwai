"""The printable poster: scan the QR in the PDF the way a phone would, and check the printed page."""

from __future__ import annotations

import cv2
import numpy as np
import pypdfium2 as pdfium
from harness import Owner, Venue, World, make_venue, sign_up
from nigiwai_api.services.poster import render_poster


def scan(pdf: bytes, scale: float = 3.0) -> str:
    """Rasterise page one and read the QR code with OpenCV's detector, as a phone camera would."""
    page = pdfium.PdfDocument(pdf)[0]
    bitmap = page.render(scale=scale).to_numpy()
    image = cv2.cvtColor(
        bitmap, cv2.COLOR_RGB2GRAY if bitmap.shape[2] == 3 else cv2.COLOR_RGBA2GRAY
    )
    text, _, _ = cv2.QRCodeDetector().detectAndDecode(image)
    return text


async def fetch(owner: Owner, venue: Venue, size: str = "a4") -> bytes:
    r = await owner.get(f"/qr-points/{venue.qr['id']}/poster.pdf", params={"size": size})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    return r.content


async def test_the_poster_qr_scans_to_the_survey_url_in_both_sizes(world: World) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner, reward={"title": "A free coffee"})
    for size in ("a4", "a6"):
        pdf = await fetch(owner, venue, size)
        assert pdf.startswith(b"%PDF")
        assert scan(pdf) == venue.qr["url"], size


async def test_page_size_and_embedded_fonts(world: World) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    a4 = pdfium.PdfDocument(await fetch(owner, venue, "a4"))[0].get_size()
    a6 = pdfium.PdfDocument(await fetch(owner, venue, "a6"))[0].get_size()
    assert (round(a4[0]), round(a4[1])) == (595, 842) and (round(a6[0]), round(a6[1])) == (298, 420)
    assert b"BricolageGrotesque" in await fetch(owner, venue)


async def test_a_name_the_font_cannot_draw_still_gives_a_working_poster(world: World) -> None:
    owner = await sign_up(world)
    for name in ("渋谷ライブハウス", "مقهى النجوم", "Café Zoë Ünïcode", "X" * 120):
        b = await owner.post("/businesses", json={"name": name, "type": "bar"})
        loc = await owner.post(f"/businesses/{b.json()['id']}/locations", json={"name": name})
        qr = (
            await owner.post(f"/locations/{loc.json()['id']}/qr-points", json={"label": name[:40]})
        ).json()
        r = await owner.get(f"/qr-points/{qr['id']}/poster.pdf")
        assert r.status_code == 200, (name, r.text)
        assert scan(r.content) == qr["url"], name


async def test_poster_is_refused_for_revoked_codes_and_bad_sizes(world: World) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    assert (
        await owner.get(f"/qr-points/{venue.qr['id']}/poster.pdf", params={"size": "a3"})
    ).status_code == 422
    await owner.post(f"/qr-points/{venue.qr['id']}/revoke")
    assert (await owner.get(f"/qr-points/{venue.qr['id']}/poster.pdf")).status_code == 409


def test_the_renderer_is_deterministic_in_content() -> None:
    kwargs = {
        "business": "The Lantern",
        "location": "Bar",
        "url": "https://nigiwai.test/s/AbCdEfGhIjKlMnOpQrStUvWx",
    }
    first = render_poster(**kwargs)  # type: ignore[arg-type]
    assert scan(first) == kwargs["url"]
    np.testing.assert_array_equal(
        pdfium.PdfDocument(first)[0].render(scale=1).to_numpy(),
        pdfium.PdfDocument(render_poster(**kwargs))[0].render(scale=1).to_numpy(),  # type: ignore[arg-type]
    )

"""Build the branded roof-proposal PDF (reportlab).

``build_proposal_pdf(report, customer)`` -> PDF bytes. ``report`` is the output
of :func:`roofwall.property_report.build_property_report`; ``customer`` is
``{name/first_name/last_name, email, phone, address}``. Company-branded only.

Four pages: Cover · About NSR · Scope of Work · Package Options + signature.
Pure given its inputs (no network) — the cover photo is passed in as bytes.
"""

from __future__ import annotations

import datetime
import io
import os
from typing import Any, Dict, List, Optional

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from roofwall.proposal.branding import COMPANY, NSR_BLUE, NSR_BLUE_DARK

PAGE_W, PAGE_H = letter  # 612 x 792
MARGIN = 40
BLUE = HexColor(NSR_BLUE)
BLUE_DARK = HexColor(NSR_BLUE_DARK)
DARK = HexColor("#0A0E14")
CHARCOAL = HexColor("#121A24")
INK = HexColor("#101820")
MUTED = HexColor("#5F6B7A")
LIGHT = HexColor("#F1F5F9")
LINE = HexColor("#E2E8F0")

_ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "assets")
# Downscaled logo for PDF embedding (falls back to the full-res asset).
_LOGO = os.path.join(_ASSETS, "nsr-logo-pdf.png")
if not os.path.exists(_LOGO):
    _LOGO = os.path.join(_ASSETS, "nsr-logo.png")
try:
    _LOGO_READER = ImageReader(_LOGO)   # cache -> reportlab embeds the image once
except Exception:  # noqa: BLE001
    _LOGO_READER = None


def _wrap(c, text, font, size, max_w) -> List[str]:
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if c.stringWidth(t, font, size) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _para(c, text, x, y, font, size, max_w, leading, color=INK) -> float:
    c.setFont(font, size)
    c.setFillColor(color)
    for line in _wrap(c, text, font, size, max_w):
        c.drawString(x, y, line)
        y -= leading
    return y


def _logo(c, x, y, h, *, on_light=False):
    if _LOGO_READER is None:
        return 0
    try:
        iw, ih = _LOGO_READER.getSize()
        w = h * iw / ih
        if on_light:   # white logo needs a dark chip to be visible on white bg
            c.setFillColor(CHARCOAL)
            c.roundRect(x - 12, y - 10, w + 24, h + 20, 8, fill=1, stroke=0)
        c.drawImage(_LOGO_READER, x, y, width=w, height=h, mask="auto", preserveAspectRatio=True)
        return w
    except Exception:  # noqa: BLE001
        return 0


def _money(v) -> str:
    try:
        return f"${int(round(float(v))):,}"
    except (TypeError, ValueError):
        return "—"


# --------------------------------------------------------------------------- #

def _cover(c, report, customer, cover_image, date_str):
    c.setFillColor(DARK)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)

    photo_top, photo_bot = PAGE_H, 330
    ph = photo_top - photo_bot
    if cover_image:
        try:
            c.drawImage(ImageReader(io.BytesIO(cover_image)), 0, photo_bot, width=PAGE_W,
                        height=ph, preserveAspectRatio=False, mask="auto")
        except Exception:  # noqa: BLE001
            cover_image = None
    if not cover_image:
        c.setFillColor(CHARCOAL)
        c.rect(0, photo_bot, PAGE_W, ph, fill=1, stroke=0)
    # darken for legible white text (left-heavy)
    c.setFillColor(HexColor("#050A10"))
    c.setFillAlpha(0.42); c.rect(0, photo_bot, PAGE_W, ph, fill=1, stroke=0)
    c.setFillAlpha(0.38); c.rect(0, photo_bot, PAGE_W * 0.62, ph, fill=1, stroke=0)
    c.setFillAlpha(1)

    # Prepared-for block (over the photo)
    x, y = MARGIN, photo_bot + 250
    c.setFillColor(BLUE); c.setFont("Helvetica-Bold", 11)
    c.drawString(x, y, "PREPARED FOR")
    y -= 22
    c.setFillColor(white); c.setFont("Helvetica-Bold", 18)
    c.drawString(x, y, customer.get("name") or "Homeowner"); y -= 20
    c.setFont("Helvetica", 12)
    for ln in [customer.get("email"), customer.get("phone"),
               (report.get("property") or {}).get("address") or customer.get("address")]:
        if ln:
            c.drawString(x, y, str(ln)); y -= 17

    # Proposal title + date
    c.setFillColor(white); c.setFont("Helvetica-Bold", 44)
    c.drawString(MARGIN, photo_bot + 74, "Proposal")
    c.setStrokeColor(BLUE); c.setLineWidth(1)
    c.roundRect(MARGIN, photo_bot + 40, 150, 26, 4, fill=0, stroke=1)
    c.setFillColor(white); c.setFont("Helvetica", 12)
    c.drawString(MARGIN + 12, photo_bot + 48, date_str)

    # Blue divider
    c.setFillColor(BLUE); c.rect(0, photo_bot - 8, PAGE_W, 8, fill=1, stroke=0)

    # Bottom white company block
    c.setFillColor(white); c.rect(0, 0, PAGE_W, photo_bot - 8, fill=1, stroke=0)
    bx, by = MARGIN, photo_bot - 60
    c.setFillColor(BLUE); c.rect(bx - 12, by - 78, 3, 96, fill=1, stroke=0)
    c.setFillColor(INK); c.setFont("Helvetica-Bold", 15)
    c.drawString(bx, by, COMPANY["name"]); by -= 20
    c.setFillColor(MUTED); c.setFont("Helvetica", 11)
    for ln in [COMPANY["tagline"], COMPANY["phone"], COMPANY["email"], COMPANY["license"]]:
        c.drawString(bx, by, ln); by -= 16
    _logo(c, PAGE_W - MARGIN - 96, photo_bot - 116, 64, on_light=True)
    c.showPage()


def _about(c):
    c.setFillColor(white); c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    # Dark hero band
    band_h = 200
    c.setFillColor(CHARCOAL); c.rect(0, PAGE_H - band_h, PAGE_W, band_h, fill=1, stroke=0)
    lw = _logo(c, MARGIN, PAGE_H - 60, 40)
    c.setFillColor(BLUE); c.setFont("Helvetica-Bold", 13)
    c.drawString(MARGIN + lw + 14, PAGE_H - 42, COMPANY["name"])
    c.setFillColor(white); c.setFont("Helvetica-Bold", 24)
    _para(c, COMPANY["tagline"], MARGIN, PAGE_H - 92, "Helvetica-Bold", 22, PAGE_W - 2 * MARGIN, 26, white)
    c.setFillColor(HexColor("#C7D2DD"))
    _para(c, COMPANY["who_we_are"], MARGIN, PAGE_H - 150, "Helvetica", 11, PAGE_W - 2 * MARGIN, 15,
          HexColor("#C7D2DD"))

    # Certification
    y = PAGE_H - band_h - 34
    c.setFillColor(INK); c.setFont("Helvetica-Bold", 15)
    c.drawString(MARGIN, y, "Why Choose New Standard Restoration")
    y -= 26
    c.setFillColor(LIGHT); c.roundRect(MARGIN, y - 18, PAGE_W - 2 * MARGIN, 30, 6, fill=1, stroke=0)
    c.setFillColor(BLUE_DARK); c.setFont("Helvetica-Bold", 12)
    c.drawString(MARGIN + 14, y - 8, "✓  " + COMPANY["certification"])
    y -= 44

    # Feature cards 2x2
    cw = (PAGE_W - 2 * MARGIN - 16) / 2
    ch = 74
    for i, (title, body) in enumerate(COMPANY["features"][:4]):
        cx = MARGIN + (i % 2) * (cw + 16)
        cy = y - (i // 2) * (ch + 14)
        c.setFillColor(LIGHT); c.roundRect(cx, cy - ch, cw, ch, 8, fill=1, stroke=0)
        c.setFillColor(BLUE_DARK); c.setFont("Helvetica-Bold", 12)
        c.drawString(cx + 14, cy - 22, title)
        c.setFillColor(MUTED)
        _para(c, body, cx + 14, cy - 40, "Helvetica", 9.5, cw - 28, 12, MUTED)
    y = y - 2 * (ch + 14) - 20

    # Testimonials
    c.setFillColor(BLUE_DARK); c.setFont("Helvetica-Bold", 13)
    c.drawString(MARGIN, y, "What homeowners say"); y -= 22
    for quote, who, where in COMPANY["testimonials"][:2]:
        c.setFillColor(HexColor("#F7F9FC")); c.roundRect(MARGIN, y - 58, PAGE_W - 2 * MARGIN, 58, 6, fill=1, stroke=0)
        ny = _para(c, '"' + quote + '"', MARGIN + 14, y - 18, "Helvetica-Oblique", 10,
                   PAGE_W - 2 * MARGIN - 28, 13, INK)
        c.setFillColor(BLUE_DARK); c.setFont("Helvetica-Bold", 10)
        c.drawString(MARGIN + 14, ny - 2, f"{who} — {where}   ★★★★★")
        y -= 72

    # Contact footer
    c.setFillColor(CHARCOAL); c.rect(0, 0, PAGE_W, 70, fill=1, stroke=0)
    c.setFillColor(white); c.setFont("Helvetica-Bold", 11)
    c.drawString(MARGIN, 44, "Contact us")
    c.setFillColor(HexColor("#C7D2DD")); c.setFont("Helvetica", 10)
    c.drawString(MARGIN, 26, f"{COMPANY['phone']}   |   {COMPANY['email']}   |   {COMPANY['website']}")
    c.drawString(MARGIN, 12, COMPANY["address"])
    _logo(c, PAGE_W - MARGIN - 90, 16, 40)
    c.showPage()


def _header_bar(c, title):
    c.setFillColor(white); c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    c.setFillColor(BLUE); c.rect(0, PAGE_H - 8, PAGE_W, 8, fill=1, stroke=0)
    c.setFillColor(INK); c.setFont("Helvetica-Bold", 26)
    c.drawString(MARGIN, PAGE_H - 54, title)


def _scope(c, report):
    _header_bar(c, "Scope of Work")
    snap = report.get("roof_snapshot") or {}
    pd = report.get("property_details") or {}
    c.setFillColor(MUTED); c.setFont("Helvetica", 12)
    c.drawString(MARGIN, PAGE_H - 74, "Complete roof replacement — " +
                 str((report.get("property") or {}).get("address") or ""))

    # Measurement chips
    chips = []
    if snap.get("total_squares"):
        chips.append(("Roof size", f"{round(snap['total_squares'])} squares"))
    if snap.get("total_sloped_sqft"):
        chips.append(("Area", f"~{int(snap['total_sloped_sqft']):,} ft²"))
    if snap.get("predominant_pitch"):
        chips.append(("Pitch", str(snap["predominant_pitch"])))
    if snap.get("structure_complexity"):
        chips.append(("Complexity", str(snap["structure_complexity"])))
    if pd.get("roof_cover"):
        chips.append(("Current roof", str(pd["roof_cover"])))
    if pd.get("year_built"):
        chips.append(("Year built", str(pd["year_built"])))
    y = PAGE_H - 110
    cw = (PAGE_W - 2 * MARGIN - 3 * 10) / 4
    for i, (l, v) in enumerate(chips[:8]):
        cx = MARGIN + (i % 4) * (cw + 10)
        cy = y - (i // 4) * 60
        c.setFillColor(LIGHT); c.roundRect(cx, cy - 46, cw, 46, 6, fill=1, stroke=0)
        c.setFillColor(INK); c.setFont("Helvetica-Bold", 14)
        c.drawString(cx + 10, cy - 24, str(v))
        c.setFillColor(MUTED); c.setFont("Helvetica", 8.5)
        c.drawString(cx + 10, cy - 38, l.upper())
    y = y - (1 if len(chips) <= 4 else 2) * 60 - 24

    c.setFillColor(INK); c.setFont("Helvetica-Bold", 15)
    c.drawString(MARGIN, y, "Roof Replacement — included in every package"); y -= 24
    for item in COMPANY["scope_of_work"]:
        c.setFillColor(BLUE_DARK); c.setFont("Helvetica-Bold", 11)
        c.drawString(MARGIN, y, "✓")
        y = _para(c, item, MARGIN + 18, y, "Helvetica", 10.5, PAGE_W - 2 * MARGIN - 18, 14, HexColor("#33404D"))
        y -= 6
    c.showPage()


def _packages(c, report, customer, date_str):
    _header_bar(c, "Your Roof Replacement Options")
    c.setFillColor(MUTED); c.setFont("Helvetica", 12)
    c.drawString(MARGIN, PAGE_H - 74, "Choose the package that's right for you — every option includes the full scope of work.")

    estimates = ((report.get("quote") or {}).get("estimates")) or []
    n = max(1, len(estimates))
    gap = 12
    cw = (PAGE_W - 2 * MARGIN - gap * (n - 1)) / n
    top = PAGE_H - 100
    card_h = 246
    for i, e in enumerate(estimates):
        cx = MARGIN + i * (cw + gap)
        featured = e.get("key") == "best"
        c.setFillColor(HexColor("#F7F9FC"))
        c.roundRect(cx, top - card_h, cw, card_h, 10, fill=1, stroke=0)
        if featured:
            c.setStrokeColor(BLUE); c.setLineWidth(2)
            c.roundRect(cx, top - card_h, cw, card_h, 10, fill=0, stroke=1)
            c.setFillColor(BLUE); c.roundRect(cx + 12, top - 24, 96, 18, 9, fill=1, stroke=0)
            c.setFillColor(HexColor("#06131C")); c.setFont("Helvetica-Bold", 8)
            c.drawString(cx + 20, top - 20, "RECOMMENDED")
        ty = top - 44
        c.setFillColor(INK); c.setFont("Helvetica-Bold", 18)
        c.drawString(cx + 14, ty, str(e.get("name", ""))); ty -= 26
        c.setFillColor(BLUE_DARK); c.setFont("Helvetica-Bold", 15)
        c.drawString(cx + 14, ty, str(e.get("price_display", _money(e.get("price"))))); ty -= 20
        c.setFillColor(MUTED); c.setFont("Helvetica", 8.5)
        if e.get("price_per_square"):
            c.drawString(cx + 14, ty, f"~${int(e['price_per_square']):,}/square installed")
        ty -= 16
        c.setStrokeColor(LINE); c.line(cx + 14, ty, cx + cw - 14, ty); ty -= 16
        for feat in (e.get("features") or [])[:6]:
            c.setFillColor(BLUE_DARK); c.setFont("Helvetica-Bold", 9)
            c.drawString(cx + 14, ty, "✓")
            ny = _para(c, feat, cx + 26, ty, "Helvetica", 9, cw - 40, 11.5, HexColor("#33404D"))
            ty = ny - 3

    # Confidence + signature
    conf = report.get("confidence") or {}
    y = top - card_h - 26
    if conf.get("level"):
        c.setFillColor(MUTED); c.setFont("Helvetica", 10)
        c.drawString(MARGIN, y, f"Estimate confidence: {conf.get('level')}  ({conf.get('accuracy_text', '')})")
    y -= 30
    c.setFillColor(INK); c.setFont("Helvetica-Bold", 13)
    c.drawString(MARGIN, y, "Accept your proposal"); y -= 8
    c.setStrokeColor(INK); c.setLineWidth(1)
    c.line(MARGIN, y - 34, MARGIN + 250, y - 34)
    c.line(PAGE_W - MARGIN - 180, y - 34, PAGE_W - MARGIN, y - 34)
    c.setFillColor(MUTED); c.setFont("Helvetica", 9)
    c.drawString(MARGIN, y - 46, "Signature — " + (customer.get("name") or "Homeowner"))
    c.drawString(PAGE_W - MARGIN - 180, y - 46, "Package selected")
    y -= 74
    c.setFillColor(MUTED); c.setFont("Helvetica-Oblique", 8.5)
    disc = ((report.get("disclaimer")) or "RoofNow instant estimates are budgetary and subject to field verification.")
    _para(c, disc, MARGIN, y, "Helvetica-Oblique", 8.5, PAGE_W - 2 * MARGIN, 11, MUTED)

    # footer
    c.setFillColor(CHARCOAL); c.rect(0, 0, PAGE_W, 30, fill=1, stroke=0)
    c.setFillColor(HexColor("#C7D2DD")); c.setFont("Helvetica", 9)
    c.drawString(MARGIN, 11, f"{COMPANY['name']}   |   {COMPANY['phone']}   |   {COMPANY['website']}   |   {COMPANY['license']}")
    c.showPage()


def build_proposal_pdf(
    report: Dict[str, Any],
    customer: Dict[str, Any],
    *,
    cover_image: Optional[bytes] = None,
    date_str: Optional[str] = None,
) -> bytes:
    """Render the branded 4-page proposal to PDF bytes."""
    if not date_str:
        date_str = datetime.date.today().strftime("%B %d, %Y")
    customer = dict(customer or {})
    if not customer.get("name"):
        customer["name"] = " ".join(x for x in (customer.get("first_name"),
                                                 customer.get("last_name")) if x) or "Homeowner"
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setTitle("Roof Replacement Proposal — New Standard Restoration")
    _cover(c, report, customer, cover_image, date_str)
    _about(c)
    _scope(c, report)
    _packages(c, report, customer, date_str)
    c.save()
    return buf.getvalue()

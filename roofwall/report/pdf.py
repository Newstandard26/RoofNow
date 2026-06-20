"""Branded PDF report (optional, requires the ``report`` extra: reportlab).

Kept import-light: reportlab is imported inside the function so the rest of
the package works without it installed.
"""

from __future__ import annotations

from roofwall.measurement.engine import RoofReport
from roofwall.report.render import azimuth_to_cardinal


def write_pdf(report: RoofReport, path: str, *, address: str | None = None) -> str:
    """Render ``report`` to a simple branded PDF at ``path``. Returns path."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.units import inch
        from reportlab.pdfgen import canvas
    except ImportError as exc:  # pragma: no cover - optional dep
        raise RuntimeError(
            "PDF output needs the 'report' extra: pip install roofwall[report]"
        ) from exc

    c = canvas.Canvas(path, pagesize=letter)
    width, height = letter
    y = height - inch

    c.setFont("Helvetica-Bold", 16)
    c.drawString(inch, y, "Roof Measurement Report")
    y -= 0.3 * inch
    if address:
        c.setFont("Helvetica", 10)
        c.drawString(inch, y, address)
        y -= 0.4 * inch

    c.setFont("Helvetica-Bold", 10)
    c.drawString(inch, y, "Facet")
    c.drawString(1.8 * inch, y, "Pitch")
    c.drawString(2.6 * inch, y, "Facing")
    c.drawString(3.6 * inch, y, "Sloped ft²")
    c.drawString(5.0 * inch, y, "Squares")
    y -= 0.05 * inch
    c.line(inch, y, 6.2 * inch, y)
    y -= 0.2 * inch

    c.setFont("Helvetica", 10)
    for i, f in enumerate(report.facets, 1):
        c.drawString(inch, y, str(i))
        c.drawString(1.8 * inch, y, f.pitch.label())
        c.drawString(2.6 * inch, y, azimuth_to_cardinal(f.azimuth_deg))
        c.drawRightString(4.6 * inch, y, f"{f.sloped_area_sqft:,.0f}")
        c.drawRightString(5.6 * inch, y, f"{f.squares:.2f}")
        y -= 0.22 * inch

    y -= 0.2 * inch
    c.setFont("Helvetica-Bold", 11)
    c.drawString(inch, y, f"Total: {report.total_squares:.2f} squares")
    y -= 0.22 * inch
    c.drawString(
        inch,
        y,
        f"Order {report.order_squares} squares "
        f"(incl. {report.waste_pct * 100:.0f}% waste)",
    )
    c.showPage()
    c.save()
    return path

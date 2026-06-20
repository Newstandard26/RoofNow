"""Serialize a RoofReport to JSON-able dict and a human-readable text block.

The PDF renderer (reportlab) lives in :mod:`roofwall.report.pdf` and is
optional; JSON/text here are dependency-free.
"""

from __future__ import annotations

from typing import Any

from roofwall.measurement.engine import RoofReport

_AZIMUTH_CARDINALS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def azimuth_to_cardinal(azimuth_deg: float) -> str:
    """Map an azimuth in degrees to an 8-point cardinal label."""
    idx = int((azimuth_deg % 360.0) / 45.0 + 0.5) % 8
    return _AZIMUTH_CARDINALS[idx]


def report_to_dict(
    report: RoofReport, *, meta: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Convert a report into a plain dict suitable for ``json.dumps``."""
    facets = [
        {
            "pitch": f.pitch.label(),
            "pitch_degrees": round(f.pitch.degrees, 2),
            "azimuth_degrees": round(f.azimuth_deg, 1),
            "facing": azimuth_to_cardinal(f.azimuth_deg),
            "footprint_area_sqft": round(f.footprint_area_sqft, 1),
            "sloped_area_sqft": round(f.sloped_area_sqft, 1),
            "squares": round(f.squares, 2),
            "confidence": round(f.confidence, 2),
            "needs_qa": f.needs_qa,
            "source": f.source,
        }
        for f in report.facets
    ]
    out: dict[str, Any] = {
        "roof": {
            "total_footprint_sqft": round(report.total_footprint_sqft, 1),
            "total_sloped_sqft": round(report.total_sloped_sqft, 1),
            "total_squares": round(report.total_squares, 2),
            "waste_pct": report.waste_pct,
            "order_squares": report.order_squares,
            "predominant_pitch": (
                report.predominant_pitch.label()
                if report.predominant_pitch
                else None
            ),
            "facet_count": len(report.facets),
            "min_confidence": round(report.min_confidence, 2),
            "facets_needing_qa": len(report.facets_needing_qa),
        },
        "facets": facets,
    }
    if meta:
        out["meta"] = meta
    return out


def report_to_text(report: RoofReport, *, address: str | None = None) -> str:
    """Render a concise, fixed-width text summary."""
    lines: list[str] = []
    lines.append("=" * 56)
    lines.append("ROOF MEASUREMENT REPORT")
    if address:
        lines.append(f"Address: {address}")
    lines.append("=" * 56)
    lines.append("")
    lines.append(f"{'Facet':<6}{'Pitch':<8}{'Facing':<8}{'Sloped ft²':>12}{'Squares':>10}")
    lines.append("-" * 56)
    for i, f in enumerate(report.facets, 1):
        flag = " *" if f.needs_qa else ""
        lines.append(
            f"{i:<6}{f.pitch.label():<8}{azimuth_to_cardinal(f.azimuth_deg):<8}"
            f"{f.sloped_area_sqft:>12,.0f}{f.squares:>10.2f}{flag}"
        )
    lines.append("-" * 56)
    lines.append(f"Total sloped area : {report.total_sloped_sqft:>10,.0f} ft²")
    lines.append(f"Total squares     : {report.total_squares:>10.2f}")
    lines.append(f"Waste factor      : {report.waste_pct * 100:>10.0f} %")
    lines.append(f"Squares to order  : {report.order_squares:>10d}")
    if report.predominant_pitch:
        lines.append(f"Predominant pitch : {report.predominant_pitch.label():>10}")
    if report.facets_needing_qa:
        lines.append("")
        lines.append(f"* {len(report.facets_needing_qa)} facet(s) flagged for human QA (low confidence)")
    lines.append("=" * 56)
    return "\n".join(lines)

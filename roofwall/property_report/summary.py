"""AI summary + "why this estimate" — natural-language explanation of the data.

Deterministic, template-driven text generated from the real measurement + quote
(no external LLM call), so the homeowner-facing narrative always matches the
numbers it sits next to. Pure functions; fully unit-testable.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

ROOFING_SQUARE_SQFT = 100.0


def _sqft(squares: Optional[float]) -> Optional[int]:
    if not isinstance(squares, (int, float)) or squares <= 0:
        return None
    return int(round(squares * ROOFING_SQUARE_SQFT))


def _confidence_sentence(confidence: Dict[str, Any]) -> str:
    band = (confidence or {}).get("band")
    pct = (confidence or {}).get("confidence_pct")
    if band == "high":
        return (f"Our aerial measurements came back clean, so we're highly confident "
                f"in this estimate ({pct}% confidence).")
    if band == "medium":
        return (f"We measured most of your roof from imagery ({pct}% confidence); a "
                f"free on-site verification will lock in the exact figure.")
    return ("We couldn't fully trace your roof from imagery, so this is a budgetary "
            "range — a free on-site verification will confirm your exact estimate.")


def build_ai_summary(report: Dict[str, Any], quote: Dict[str, Any]) -> Dict[str, Any]:
    """A short, data-grounded narrative + scannable highlights."""
    roof = report.get("roof") or {}
    confidence = quote.get("confidence") or {}
    pr = quote.get("price_range") or {}

    squares = roof.get("total_squares")
    sqft = _sqft(squares)
    pitch = roof.get("predominant_pitch")
    complexity = roof.get("structure_complexity")
    facets = roof.get("facet_count")

    parts: List[str] = []
    if sqft:
        size = f"approximately {sqft:,} sq ft"
        if squares:
            size += f" (about {round(squares)} squares)"
        face = f" across {facets} roof faces" if facets else ""
        pitchtxt = f" at a {pitch} pitch" if pitch else ""
        comptxt = f", a {complexity.lower()} roof" if complexity else ""
        parts.append(f"RoofNow measured your roof at {size}{face}{pitchtxt}{comptxt}.")
    else:
        parts.append("RoofNow located your property and prepared a budgetary estimate "
                     "from its footprint.")
    if pr.get("display"):
        parts.append(f"Based on those measurements and local New Standard Restoration "
                     f"pricing, a full replacement is estimated at {pr['display']}.")
    parts.append(_confidence_sentence(confidence))

    highlights: List[Dict[str, str]] = []
    if sqft:
        highlights.append({"label": "Roof area", "value": f"~{sqft:,} sq ft"})
    if pitch:
        highlights.append({"label": "Pitch", "value": str(pitch)})
    if complexity:
        highlights.append({"label": "Complexity", "value": str(complexity)})
    if facets:
        highlights.append({"label": "Roof faces", "value": str(facets)})

    return {"text": " ".join(parts), "highlights": highlights}


def build_price_explanation(report: Dict[str, Any], quote: Dict[str, Any]) -> Dict[str, Any]:
    """"Why this estimate?" — the measured drivers behind the price."""
    roof = report.get("roof") or {}
    measurement = quote.get("measurement") or {}
    drivers: List[Dict[str, str]] = []

    order_sq = measurement.get("order_squares") or roof.get("order_squares")
    if order_sq:
        drivers.append({
            "label": "Roof size",
            "value": f"{round(order_sq)} squares to install",
            "note": "Measured area plus a standard waste factor.",
        })
    pitch = roof.get("predominant_pitch")
    if pitch:
        drivers.append({
            "label": "Pitch",
            "value": str(pitch),
            "note": "Steeper roofs take more labor, staging, and safety setup.",
        })
    complexity = roof.get("structure_complexity")
    if complexity:
        drivers.append({
            "label": "Complexity",
            "value": str(complexity),
            "note": "More valleys, hips, and facets mean more cutting, flashing, and waste.",
        })
    waste = roof.get("suggested_waste_pct") or measurement.get("suggested_waste_pct")
    if waste:
        drivers.append({
            "label": "Waste factor",
            "value": f"{waste}%",
            "note": "Material overage for cuts, starter, and ridge.",
        })

    return {
        "headline": "Why this estimate?",
        "basis": ("Your price is the installed cost per roofing square multiplied by your "
                  "measured roof size, then adjusted for pitch and complexity."),
        "drivers": drivers,
    }

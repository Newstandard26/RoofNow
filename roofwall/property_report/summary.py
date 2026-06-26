"""AI summary + "why this estimate" (Phase 2.1: success framing).

Deterministic, template-driven copy generated from the real measurement + quote
(no external LLM). The language focuses on a successful analysis and homeowner
value — never on what the AI couldn't reconstruct. Pure, unit-testable.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

ROOFING_SQUARE_SQFT = 100.0


def _sqft(squares: Optional[float]) -> Optional[int]:
    if not isinstance(squares, (int, float)) or squares <= 0:
        return None
    return int(round(squares * ROOFING_SQUARE_SQFT))


def build_ai_summary(report: Dict[str, Any], quote: Dict[str, Any]) -> Dict[str, Any]:
    """A confident, data-grounded narrative + scannable highlights."""
    roof = report.get("roof") or {}
    confidence = quote.get("confidence") or {}
    reliable = confidence.get("reliable", True)

    squares = roof.get("total_squares")
    sqft = _sqft(squares)
    pitch = roof.get("predominant_pitch")
    complexity = roof.get("structure_complexity")
    facets = roof.get("facet_count")

    if not reliable or not sqft:
        text = ("RoofNow analyzed your property using aerial imagery and AI roof "
                "measurement technology. To give you the most accurate estimate for this "
                "home, a New Standard Restoration expert will measure your roof during a "
                "complimentary on-site verification.")
    else:
        size = f"approximately {round(squares)} squares"
        pitchtxt = f" with a dominant {pitch} pitch" if pitch else ""
        text = (
            "RoofNow analyzed your property using aerial imagery and AI roof measurement "
            f"technology. Based on the available data, your roof is estimated at {size}"
            f"{pitchtxt}. The estimate below represents a realistic replacement cost range "
            "for roofs of similar size and complexity in your area. Your free roof "
            "verification confirms field conditions such as decking, flashing, "
            "ventilation, and material selections before your final proposal."
        )

    highlights: List[Dict[str, str]] = []
    if sqft:
        highlights.append({"label": "Roof area", "value": f"~{sqft:,} sq ft"})
    if squares:
        highlights.append({"label": "Roofing squares", "value": f"{round(squares)} sq"})
    if pitch:
        highlights.append({"label": "Pitch", "value": str(pitch)})
    if complexity:
        highlights.append({"label": "Complexity", "value": str(complexity)})

    return {"text": text, "highlights": highlights}


def build_price_explanation(report: Dict[str, Any], quote: Dict[str, Any]) -> Dict[str, Any]:
    """"Why this estimate?" — homeowner-language price drivers (no jargon)."""
    roof = report.get("roof") or {}
    measurement = quote.get("measurement") or {}
    drivers: List[Dict[str, str]] = []

    order_sq = measurement.get("order_squares") or roof.get("order_squares")
    squares = measurement.get("total_squares") or roof.get("total_squares")
    if squares:
        drivers.append({
            "label": "Roof size",
            "value": f"about {round(squares)} squares",
            "note": "The bigger the roof, the more material and labor it takes.",
        })
    complexity = roof.get("structure_complexity")
    if complexity:
        drivers.append({
            "label": "Roof complexity",
            "value": str(complexity),
            "note": "More angles and edges add cutting, detail work, and time.",
        })
    pitch = roof.get("predominant_pitch")
    if pitch:
        drivers.append({
            "label": "Roof steepness",
            "value": str(pitch),
            "note": "Steeper roofs take more setup and labor to install safely.",
        })
    drivers.append({
        "label": "Material quality",
        "value": "Good · Better · Best",
        "note": "Your shingle line and warranty — you choose the package below.",
    })
    drivers.append({
        "label": "Labor & accessories",
        "value": "Included",
        "note": "Tear-off, underlayment, flashing, vents, and cleanup are built in.",
    })

    return {
        "headline": "Why this estimate?",
        "basis": ("Your range reflects your roof's size, shape, and steepness, the material "
                  "package you choose, and local installed pricing."),
        "drivers": drivers,
    }

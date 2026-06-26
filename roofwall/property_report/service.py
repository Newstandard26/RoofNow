"""build_property_report — assemble the homeowner Property Intelligence Report.

Reuses the existing pipeline end-to-end (no duplicated calculation):

    measure_address(...)  -> measurement report
    build_quote(report)   -> confidence + Good/Better/Best (reuses pricing+confidence)

then shapes the ten report sections. One measurement + one quote per report.

Failure mode (per 03_BACKEND_IMPLEMENTATION_PLAN.md): if measurement is
unavailable / the roof can't be found, return a low-confidence report whose
recommended next step is a manual on-site verification — never a fabricated
number.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from roofwall.property_report.health import build_roof_health
from roofwall.property_report.recommendation import build_recommendation
from roofwall.property_report.schema import REPORT_DISCLAIMER, brand_block
from roofwall.property_report.storm import build_storm_exposure
from roofwall.property_report.summary import build_ai_summary, build_price_explanation


def _roof_snapshot(report: Dict[str, Any]) -> Dict[str, Any]:
    roof = report.get("roof") or {}
    squares = roof.get("total_squares")
    sloped = round(squares * 100.0) if isinstance(squares, (int, float)) else None
    return {
        "total_squares": squares,
        "order_squares": roof.get("order_squares"),
        "total_sloped_sqft": sloped,
        "predominant_pitch": roof.get("predominant_pitch"),
        "structure_complexity": roof.get("structure_complexity"),
        "facet_count": roof.get("facet_count"),
        "suggested_waste_pct": roof.get("suggested_waste_pct"),
    }


def _property_block(report: Dict[str, Any], address: Optional[str]) -> Dict[str, Any]:
    return {
        "address": report.get("address") or address,
        "lat": report.get("lat"),
        "lng": report.get("lng"),
        "data_source": report.get("data_source"),
        "imagery_date": report.get("imagery_date"),
    }


def _lead_block(lead: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not lead:
        return None
    return {
        "name": lead.get("name") or " ".join(
            p for p in (lead.get("first_name"), lead.get("last_name")) if p),
        "email": lead.get("email"),
        "phone": lead.get("phone"),
    }


def _manual_review_report(address: Optional[str], lead: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Measurement unavailable -> honest low-confidence report + manual CTA."""
    confidence = {
        "confidence_pct": 35, "band": "low", "margin_of_error_pct": 30,
        "reasons": [],
        "warnings": ["We couldn't measure this roof from aerial imagery — a free on-site "
                     "verification will produce your estimate."],
    }
    out: Dict[str, Any] = {
        "brand": brand_block(),
        "status": "manual_review",
        "property": {"address": address, "lat": None, "lng": None,
                     "data_source": None, "imagery_date": None},
        "roof_snapshot": _roof_snapshot({}),
        "confidence": confidence,
        "ai_summary": {"text": ("RoofNow located your property but couldn't measure the roof "
                                "from current imagery. New Standard Restoration will prepare "
                                "your estimate during a free on-site verification."),
                       "highlights": []},
        "price_explanation": {"headline": "Why this estimate?",
                              "basis": "A precise estimate needs an on-site measurement for this property.",
                              "drivers": []},
        "quote": None,
        "roof_health": build_roof_health({}),
        "storm_exposure": build_storm_exposure({}),
        "recommended_next_step": build_recommendation(confidence, found=False),
        "disclaimer": REPORT_DISCLAIMER,
    }
    lb = _lead_block(lead)
    if lb:
        out["lead"] = lb
    return out


def build_property_report(
    address: Optional[str] = None,
    *,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    lead: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the full Property Intelligence Report for an address.

    Reuses measure_address + build_quote. Never raises.
    """
    # Imported lazily so the package is importable without the measurement stack.
    from roofwall.app import measure_address
    from roofwall.quote import build_quote

    try:
        report = measure_address(address=address, lat=lat, lng=lng)
    except Exception:  # noqa: BLE001
        report = None
    if not report:
        return _manual_review_report(address, lead)

    quote = build_quote(report)
    confidence = quote.get("confidence") or {}
    roof = report.get("roof") or {}
    found = report.get("mode") == "live" and bool(roof.get("facet_count"))

    out: Dict[str, Any] = {
        "brand": brand_block(),
        "status": "estimated" if found else "manual_review",
        "property": _property_block(report, address),
        "roof_snapshot": _roof_snapshot(report),
        "confidence": confidence,
        "ai_summary": build_ai_summary(report, quote),
        "price_explanation": build_price_explanation(report, quote),
        "quote": {
            "price_range": quote.get("price_range"),
            "estimates": quote.get("estimates"),
            "measurement": quote.get("measurement"),
        },
        "roof_health": build_roof_health(report),
        "storm_exposure": build_storm_exposure(report),
        "recommended_next_step": build_recommendation(confidence, found=found),
        "disclaimer": REPORT_DISCLAIMER,
    }
    lb = _lead_block(lead)
    if lb:
        out["lead"] = lb
    return out

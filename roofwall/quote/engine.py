"""Instant-quote engine — measurement report -> consumer-facing quote.

Glues the measurement pipeline output to the pricing + confidence engines and
shapes the result for the RoofNow landing page / ``/api/instant-quote``:

    Address -> measure_address(...) -> build_quote(report) -> {
        squares, pitch, complexity,
        confidence: { pct, band, margin, reasons, warnings },
        estimates:  [ Good, Better, Best ],
        ...
    }

This module owns no measurement or pricing logic of its own — it reuses the
existing engine (per the build brief: "Reuse current measurement engine"). It
is pure given a report dict, so it is fully unit-testable offline.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from roofwall.quote.confidence import assess
from roofwall.quote.pricing import (
    DEFAULT_PRICING,
    PricingConfig,
    estimate_tiers,
    load_pricing,
)

BRAND = "RoofNow"
POWERED_BY = "New Standard Restoration"
DISCLAIMER = (
    "This is an instant estimate based on aerial roof measurements, not a "
    "final contract price. Your exact quote is confirmed by a free on-site "
    f"inspection from {POWERED_BY}."
)


def _order_squares(roof: Dict[str, Any]) -> float:
    """The waste-inclusive squares to install. Prefer ``order_squares``; fall
    back to total squares grossed up by the suggested waste factor."""
    order = roof.get("order_squares")
    if isinstance(order, (int, float)) and order > 0:
        return float(order)
    total = float(roof.get("total_squares") or 0.0)
    waste = roof.get("suggested_waste_pct")
    if total > 0 and isinstance(waste, (int, float)):
        return total * (1.0 + waste / 100.0)
    return total


def build_quote(
    report: Dict[str, Any],
    *,
    config: Optional[PricingConfig] = None,
) -> Dict[str, Any]:
    """Build the instant quote from a measurement report dict.

    ``report`` is the output of :func:`roofwall.app.measure_address`. When
    ``config`` is omitted the active rate card is resolved via
    :func:`roofwall.quote.pricing.load_pricing` (env var / config file /
    defaults), so prices are editable without a code change.
    """
    config = config or load_pricing()
    roof = report.get("roof") or {}

    confidence = assess(report)
    order_sq = _order_squares(roof)
    pitch_label = roof.get("predominant_pitch")
    complexity = roof.get("structure_complexity")

    tiers = estimate_tiers(
        order_sq,
        pitch_label,
        complexity,
        margin_pct=confidence.margin_of_error_pct,
        config=config,
    )

    quote: Dict[str, Any] = {
        "brand": BRAND,
        "powered_by": POWERED_BY,
        "address": report.get("address"),
        "mode": report.get("mode"),
        "imagery_date": report.get("imagery_date"),
        "measurement": {
            "total_squares": roof.get("total_squares"),
            "order_squares": round(order_sq, 2) if order_sq else 0,
            "predominant_pitch": pitch_label,
            "structure_complexity": complexity,
            "facet_count": roof.get("facet_count"),
            "suggested_waste_pct": roof.get("suggested_waste_pct"),
        },
        "confidence": confidence.to_dict(),
        "estimates": [t.to_dict() for t in tiers],
        "price_range": _overall_range(tiers),
        "next_step": "Book a free inspection to lock in your exact price.",
        "disclaimer": DISCLAIMER,
    }
    return quote


def _overall_range(tiers) -> Dict[str, Any]:
    """The headline range across all tiers (cheapest low -> priciest high)."""
    priced = [t for t in tiers if t.price > 0]
    if not priced:
        return {"low": 0, "high": 0, "display": "Estimate unavailable"}
    low = min(t.price_low for t in priced)
    high = max(t.price_high for t in priced)
    return {"low": low, "high": high, "display": f"${low:,} – ${high:,}"}

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
from roofwall.quote.estimate_confidence import assess_estimate
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


def build_preview(report: Dict[str, Any]) -> Dict[str, Any]:
    """Address-only teaser: confirm we found the roof + a confidence read,
    WITHOUT revealing Good/Better/Best pricing.

    Drives step 1 of the landing page ("We found your roof" → confidence →
    "Your estimate is ready"). Pricing stays gated behind the contact form
    (:func:`build_quote`), so this deliberately omits estimates / price_range.
    """
    roof = report.get("roof") or {}
    estimate = assess_estimate(report)
    facet_count = int(roof.get("facet_count") or len(report.get("facets") or []))
    found = report.get("mode") == "live" and facet_count > 0

    return {
        "brand": BRAND,
        "powered_by": POWERED_BY,
        "found": found,
        "ready": True,
        "address": report.get("address"),
        "mode": report.get("mode"),
        "imagery_date": report.get("imagery_date"),
        "roof": {
            "total_squares": roof.get("total_squares"),
            "predominant_pitch": roof.get("predominant_pitch"),
            "structure_complexity": roof.get("structure_complexity"),
            "facet_count": facet_count,
        },
        "confidence": estimate.to_dict(),
        "headline": "We found your roof" if found else "We located your property",
        "next_step": "Enter your details to unlock your Good / Better / Best pricing.",
    }


def _order_squares(roof: Dict[str, Any], config: Optional[PricingConfig] = None) -> float:
    """The waste-inclusive squares to install.

    When the admin rate card defines a waste % for this complexity, gross the
    measured area up by it (so dashboard waste changes take effect). Otherwise
    fall back to the measured ``order_squares`` / the report's suggested waste.
    """
    total = float(roof.get("total_squares") or 0.0)
    complexity = roof.get("structure_complexity")
    waste_defaults = getattr(config, "waste_defaults", None) if config else None
    if total > 0 and isinstance(waste_defaults, dict) and complexity in waste_defaults:
        return total * (1.0 + float(waste_defaults[complexity]) / 100.0)

    order = roof.get("order_squares")
    if isinstance(order, (int, float)) and order > 0:
        return float(order)
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

    # Customer-facing Estimate Confidence drives the UI + the displayed price
    # range. Engineering confidence (geometry QA) is computed and stored, but
    # never shown to customers.
    estimate = assess_estimate(report)
    engineering = assess(report)
    order_sq = _order_squares(roof, config)
    pitch_label = roof.get("predominant_pitch")
    complexity = roof.get("structure_complexity")

    tiers = estimate_tiers(
        order_sq,
        pitch_label,
        complexity,
        margin_pct=estimate.accuracy_pct / 100.0,   # ±5/8/12% from estimate confidence
        config=config,
    )
    price_range = _overall_range(tiers)
    financing = _financing_teaser(config, price_range)
    service_area = _service_area_flag(config, report.get("address"))

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
        # Customer-facing confidence == Estimate Confidence.
        "confidence": estimate.to_dict(),
        "estimate_confidence": estimate.to_dict(),
        # Internal only (geometry QA) — stored, never rendered to customers.
        "engineering_confidence": engineering.score,
        "estimates": [t.to_dict() for t in tiers],
        "price_range": price_range,
        "financing": financing,
        "service_area": service_area,
        "next_step": "Book a free inspection to lock in your exact price.",
        "disclaimer": DISCLAIMER,
    }
    return quote


def _financing_teaser(config, price_range) -> Optional[Dict[str, Any]]:
    """Display-only "as low as $X/mo" from the admin financing settings."""
    from roofwall.quote.pricing import monthly_payment

    fin = getattr(config, "financing", None) or {}
    if not fin.get("enabled"):
        return None
    principal = (price_range or {}).get("low")
    pay = monthly_payment(principal, fin.get("apr", 0), fin.get("term_months", 0))
    if not pay:
        return None
    return {
        "enabled": True,
        "monthly": pay,
        "apr": fin.get("apr"),
        "term_months": fin.get("term_months"),
        "text": f"As low as ${pay:,}/mo with approved financing",
    }


def _service_area_flag(config, address: Optional[str]) -> Optional[Dict[str, Any]]:
    """Soft flag when an address looks outside NSR's configured service area."""
    sa = getattr(config, "service_area", None) or {}
    if not sa.get("enabled") or not address:
        return None
    addr = str(address).upper()
    states = [str(s).upper() for s in sa.get("states", []) if s]
    zips = [str(z) for z in sa.get("zip_prefixes", []) if z]
    in_area = True
    if states or zips:
        in_state = any(f", {s} " in addr or f", {s}," in addr or addr.endswith(f", {s}")
                       for s in states)
        import re as _re
        zip_match = _re.search(r"\b(\d{5})\b", addr)
        in_zip = bool(zip_match and any(zip_match.group(1).startswith(z) for z in zips))
        in_area = (in_state or not states) and (in_zip or not zips) if (states and zips) \
            else (in_state or in_zip)
    return {
        "in_area": in_area,
        "message": sa.get("message", "") if not in_area else "",
    }


def _overall_range(tiers) -> Dict[str, Any]:
    """The headline range across all tiers (cheapest low -> priciest high)."""
    priced = [t for t in tiers if t.price > 0]
    if not priced:
        return {"low": 0, "high": 0, "display": "Estimate unavailable"}
    low = min(t.price_low for t in priced)
    high = max(t.price_high for t in priced)
    return {"low": low, "high": high, "display": f"${low:,} – ${high:,}"}

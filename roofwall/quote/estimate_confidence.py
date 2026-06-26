"""Estimate Confidence — the CUSTOMER-facing confidence model (Phase 2.1).

This is deliberately NOT the engineering/geometry confidence (see
:mod:`roofwall.quote.confidence`). A homeowner doesn't care whether every ridge
and valley polygon reconstructed perfectly — they care:

    "Can I trust this estimate enough to schedule an inspection?"

So Estimate Confidence answers: *how likely is the replacement price to land
within expected field pricing?* It is driven by the things that actually move a
budgetary estimate — roof AREA and pitch, pricing completeness, imagery quality
— not polygon beauty. Google's Solar areas are reliable even when our line
reconstruction is messy, so a real aerial measurement should read "Excellent",
not "54% low".

Weighted inputs (per the Phase 2.1 spec):
    roof area confidence            40%
    pitch confidence                20%
    pricing model completeness      15%
    imagery quality                 10%
    regional pricing freshness      10%
    building identification          5%

The score maps to a customer level + an expected pricing-accuracy band; we show
the LEVEL, never a bare percentage or "low confidence" (unless the estimate
truly can't be trusted, which surfaces as "Manual Review Recommended").

The model is intentionally simple and additive so it can later be *trained* on
real RoofNow-estimate-vs-final-contract outcomes instead of heuristics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

# weight, in the order documented above
WEIGHTS = {
    "roof_area": 0.40,
    "pitch": 0.20,
    "pricing_completeness": 0.15,
    "imagery_quality": 0.10,
    "regional_pricing_freshness": 0.10,
    "building_identification": 0.05,
}

# Regional pricing is current (single live rate card today). A future admin/
# dashboard can lower this as a market's rate card ages.
DEFAULT_REGIONAL_FRESHNESS = 0.92

# Customer levels: (min_score, level, expected accuracy ± pct)
_LEVELS = [
    (0.90, "Excellent Estimate", 5),
    (0.80, "Very Good Estimate", 8),
    (0.65, "Preliminary Estimate", 12),
]
_MANUAL = ("Manual Review Recommended", 15)

_COPY = {
    "Excellent Estimate": (
        "Our AI successfully analyzed your property using aerial imagery and local "
        "pricing data. Your estimate represents a reliable budgetary replacement "
        "range. Final pricing will always be confirmed during your free on-site "
        "roof verification."
    ),
    "Very Good Estimate": (
        "Our AI analyzed your property using aerial imagery and local pricing data. "
        "Your estimate is a dependable budgetary replacement range, confirmed during "
        "your free on-site roof verification."
    ),
    "Preliminary Estimate": (
        "We generated a preliminary replacement range for your property from aerial "
        "imagery and local pricing. Your free on-site roof verification will refine "
        "it into a final proposal."
    ),
    "Manual Review Recommended": (
        "We'd like a New Standard Restoration expert to measure this roof in person "
        "to give you an accurate estimate. Your free on-site verification has no "
        "obligation."
    ),
}


@dataclass(frozen=True)
class EstimateConfidence:
    score: float                       # 0-1
    level: str                         # "Excellent Estimate" ...
    accuracy_pct: int                  # expected pricing accuracy, ± this %
    headline: str                      # short label, e.g. "Excellent"
    message: str                       # customer copy
    factors: Dict[str, float] = field(default_factory=dict)  # internal/admin

    @property
    def reliable(self) -> bool:
        return self.level != "Manual Review Recommended"

    def to_dict(self) -> Dict[str, Any]:
        """Customer-facing payload. Note: no bare 'NN%'/'low confidence'."""
        return {
            "label": "Estimate Confidence",
            "level": self.level,
            "headline": self.headline,
            "accuracy_pct": self.accuracy_pct,
            "accuracy_text": f"within approximately ±{self.accuracy_pct}%",
            "message": self.message,
            "score": round(self.score, 2),
            "reliable": self.reliable,
        }


def _imagery_score(quality) -> float:
    return {"HIGH": 1.0, "MEDIUM": 0.78, "LOW": 0.55}.get(
        str(quality).upper() if quality else "", 0.7)


def _level_for(score: float) -> tuple[str, int]:
    for threshold, level, acc in _LEVELS:
        if score >= threshold:
            return level, acc
    return _MANUAL


def assess_estimate(report: Dict[str, Any], *, pricing_complete: bool = True,
                    regional_freshness: float = DEFAULT_REGIONAL_FRESHNESS) -> EstimateConfidence:
    """Customer-facing estimate confidence for a measurement report."""
    roof = report.get("roof") or {}
    is_live = report.get("mode") == "live" and not report.get("demo_reason")
    squares = roof.get("total_squares") or 0
    has_area = bool(is_live and squares and squares > 0)

    # No trustworthy area at all -> manual review, regardless of the rest.
    if not has_area:
        return EstimateConfidence(
            score=0.4, level=_MANUAL[0], accuracy_pct=_MANUAL[1],
            headline="Manual Review", message=_COPY[_MANUAL[0]],
            factors={"roof_area": 0.0},
        )

    min_conf = roof.get("min_confidence")
    pitch = roof.get("predominant_pitch")
    facet_count = roof.get("facet_count") or 0

    # 1) Roof area — the dominant price driver. Solar areas are reliable even
    #    when polygon reconstruction is imperfect, so this stays high.
    area = 0.95
    if isinstance(min_conf, (int, float)):
        if min_conf >= 0.8:
            area = 0.98
        elif min_conf < 0.5:
            area = 0.88
    # 2) Pitch — known dominant pitch tightens the slope/labor estimate.
    pitch_s = 0.92 if pitch else 0.6
    # 3) Pricing model completeness — full rate card present.
    pricing_s = 1.0 if pricing_complete else 0.5
    # 4) Imagery quality from Solar.
    imagery_s = _imagery_score(report.get("imagery_quality"))
    # 5) Regional pricing freshness.
    regional_s = max(0.0, min(1.0, regional_freshness))
    # 6) Building identification — did we lock onto a building footprint.
    building_s = 0.9 if facet_count else 0.7

    factors = {
        "roof_area": area,
        "pitch": pitch_s,
        "pricing_completeness": pricing_s,
        "imagery_quality": imagery_s,
        "regional_pricing_freshness": regional_s,
        "building_identification": building_s,
    }
    score = sum(WEIGHTS[k] * factors[k] for k in WEIGHTS)
    level, acc = _level_for(score)
    headline = {"Excellent Estimate": "Excellent", "Very Good Estimate": "Very Good",
                "Preliminary Estimate": "Preliminary"}.get(level, "Manual Review")
    return EstimateConfidence(
        score=score, level=level, accuracy_pct=acc, headline=headline,
        message=_COPY[level], factors=factors,
    )

"""Property Intelligence Report — shape, brand, and canonical copy.

The report is a plain JSON dict (see docs/phase-2-property-intelligence). This
module owns the brand block, the legal disclaimer copy block, the list of
required top-level keys, and a light validator used by the tests — no
measurement or pricing logic lives here.
"""

from __future__ import annotations

from typing import Any, Dict, List

from roofwall.quote.engine import BRAND, POWERED_BY

# Exact copy block from docs/phase-2-property-intelligence/05_REPORT_COPY_BLOCKS.md
REPORT_DISCLAIMER = (
    "RoofNow instant estimates are budgetary and subject to field verification. "
    "Final pricing may vary based on roof access, decking condition, material "
    "selection, ventilation, flashing, code requirements, and final scope."
)

HERO_HEADLINE = "Your Roof Intelligence Report is Ready"
HERO_SUBHEADLINE = (
    "RoofNow analyzed your property using aerial imagery, roof measurement data, "
    "and local replacement pricing."
)
VERIFICATION_CTA = "Schedule Free Roof Verification"

# Top-level keys every report must carry (02_REPORT_JSON_SCHEMA.md).
REQUIRED_KEYS: List[str] = [
    "brand",
    "property",
    "roof_snapshot",
    "confidence",
    "ai_summary",
    "price_explanation",
    "quote",
    "roof_health",
    "storm_exposure",
    "recommended_next_step",
    "disclaimer",
]


def brand_block() -> Dict[str, Any]:
    """The RoofNow / NSR brand header used at the top of every report."""
    return {
        "name": BRAND,
        "powered_by": POWERED_BY,
        "headline": HERO_HEADLINE,
        "subheadline": HERO_SUBHEADLINE,
    }


def validate_report(report: Dict[str, Any]) -> List[str]:
    """Return a list of missing required keys (empty list == valid)."""
    return [k for k in REQUIRED_KEYS if k not in report]

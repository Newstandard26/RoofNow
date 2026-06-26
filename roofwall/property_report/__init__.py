"""RoofNow Phase 2 — Property Intelligence Report.

Turns a price range into a believable, homeowner-facing report that explains the
estimate and drives a booked verification inspection. Reuses the Phase 1
measurement, confidence, and pricing/quote engines; adds no calculation logic.

    build_property_report(address, lat=, lng=, lead=) -> dict
"""

from roofwall.property_report.schema import (
    HERO_HEADLINE,
    HERO_SUBHEADLINE,
    REPORT_DISCLAIMER,
    REQUIRED_KEYS,
    VERIFICATION_CTA,
    brand_block,
    validate_report,
)
from roofwall.property_report.service import build_property_report

__all__ = [
    "build_property_report",
    "brand_block",
    "validate_report",
    "REQUIRED_KEYS",
    "REPORT_DISCLAIMER",
    "HERO_HEADLINE",
    "HERO_SUBHEADLINE",
    "VERIFICATION_CTA",
]

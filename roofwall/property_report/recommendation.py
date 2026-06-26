"""Recommended next step — the conversion CTA (Phase 2.1: success framing).

Never implies the AI failed. The estimate is ready; the next step is a
complimentary verification. Driven by Estimate Confidence (reliable vs. needs a
manual review), not by geometry.
"""

from __future__ import annotations

from typing import Any, Dict

from roofwall.property_report.schema import VERIFICATION_CTA

VERIFICATION_CHECKLIST = [
    "Verify measurements",
    "Inspect roof condition",
    "Check ventilation",
    "Inspect flashing",
    "Confirm your final options",
]


def build_recommendation(confidence: Dict[str, Any], found: bool = True) -> Dict[str, Any]:
    """``confidence`` is the customer-facing Estimate Confidence dict."""
    reliable = bool((confidence or {}).get("reliable", found))

    if reliable:
        body = ("Your estimate is ready. The final step is a complimentary roof "
                "verification by a New Standard Restoration expert.")
    else:
        body = ("The final step is a complimentary roof verification by a New Standard "
                "Restoration expert, who will measure your roof in person and prepare "
                "your estimate.")

    return {
        "headline": "Your estimate is ready" if reliable else "Recommended next step",
        "body": body,
        "checklist": list(VERIFICATION_CHECKLIST),
        "free_no_obligation": "This inspection is free and carries no obligation.",
        "cta_label": VERIFICATION_CTA,
        "cta_action": "book_inspection",
    }

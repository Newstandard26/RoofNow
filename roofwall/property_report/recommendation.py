"""Recommended next step — the conversion CTA, tuned to confidence.

The next step is always "book the free verification," but the framing changes
with how confident the measurement is: a clean high-confidence roof leans on
locking in the price; a low-confidence / not-found roof leans on the
verification confirming the estimate.
"""

from __future__ import annotations

from typing import Any, Dict

from roofwall.property_report.schema import VERIFICATION_CTA


def build_recommendation(confidence: Dict[str, Any], found: bool = True) -> Dict[str, Any]:
    band = (confidence or {}).get("band")

    if not found or band == "low":
        body = ("Because we couldn't fully measure your roof from aerial imagery, a free, "
                "no-obligation on-site verification will confirm your exact estimate.")
    elif band == "medium":
        body = ("Schedule your free on-site verification — New Standard Restoration will "
                "confirm the measurements and lock in your exact price.")
    else:
        body = ("Your estimate is ready. Book a free, no-obligation verification with New "
                "Standard Restoration to lock in your price and timeline.")

    return {
        "headline": "Recommended next step",
        "body": body,
        "cta_label": VERIFICATION_CTA,
        "cta_action": "book_inspection",
    }

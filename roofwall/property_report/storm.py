"""Storm exposure section — Phase 2 placeholder.

Hail/wind event history is a future data integration. Phase 2 ships an honest
placeholder that sets the expectation and routes storm-damage assessment to the
on-site verification, rather than fabricating a storm score.
"""

from __future__ import annotations

from typing import Any, Dict


def build_storm_exposure(report: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "headline": "Storm Exposure",
        "available": False,
        "status": "coming_soon",
        "message": ("RoofNow will analyze recent hail and wind events for your area in an "
                    "upcoming release. Until then, your New Standard Restoration inspector "
                    "reviews storm damage and insurance eligibility on-site."),
    }

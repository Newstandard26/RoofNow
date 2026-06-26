"""Storm exposure section (Phase 2.1: value framing, not "coming soon").

Frames storm review as part of the free verification today. A future release can
upgrade this to live hail/wind storm intelligence.
"""

from __future__ import annotations

from typing import Any, Dict


def build_storm_exposure(report: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "headline": "Storm & damage review",
        "available": True,
        "message": ("Our inspectors will also look for signs of hail, wind damage, flashing "
                    "issues, and other conditions that may affect your roof — and review "
                    "insurance eligibility where it applies."),
    }

"""Roof health section — Phase 2 placeholder.

A real condition assessment needs on-site (or close-range) inspection, so Phase 2
ships an honest placeholder: it frames what NSR checks during the free
verification rather than inventing a condition score from aerial data.
"""

from __future__ import annotations

from typing import Any, Dict


def build_roof_health(report: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "headline": "Roof Health",
        "available": False,
        "status": "pending_inspection",
        "message": ("A detailed roof condition assessment — shingle wear, decking, "
                    "flashing, and ventilation — is performed during your free on-site "
                    "verification by New Standard Restoration."),
        "checklist": [
            "Shingle and granule wear",
            "Flashing and penetrations",
            "Decking and soft spots",
            "Attic ventilation",
        ],
    }

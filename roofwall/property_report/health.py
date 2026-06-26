"""Roof health section (Phase 2.1: a value-add, not a "placeholder").

Frames what the free on-site verification checks — positioned as added value
rather than something the AI couldn't do.
"""

from __future__ import annotations

from typing import Any, Dict


def build_roof_health(report: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "headline": "What we'll verify during your free roof assessment",
        "available": True,
        "message": ("Your aerial estimate covers size, pitch, and replacement cost. During "
                    "your complimentary on-site assessment, a New Standard Restoration "
                    "expert reviews the condition details that finalize your proposal:"),
        "checklist": [
            "Shingle and granule wear",
            "Decking and any soft spots",
            "Flashing and roof penetrations",
            "Attic ventilation",
        ],
    }

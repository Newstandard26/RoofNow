"""Engineering confidence — INTERNAL geometry/measurement QA (Phase 2.1).

This is the *engineering* confidence model: it scores how well the roof geometry
reconstructed (recovery QA, per-facet confidence, topology). It is for internal
QA, debugging, and the future admin dashboard only — it is NEVER shown to
customers. The customer-facing number is :mod:`roofwall.quote.estimate_confidence`
(Estimate Confidence), which measures expected *pricing* accuracy, not polygon
quality.

Original docstring follows:

Confidence engine — how much to trust an instant quote.

The instant quote is only as good as the measurement behind it. This module
turns the measurement report's QA signals into a single, honest verdict:

    * ``confidence_pct``     0-100, how confident we are in the measured roof
    * ``band``               "high" / "medium" / "low" (drives UI + copy)
    * ``margin_of_error_pct``  +/- this much on the price (feeds the pricing range)
    * ``reasons``            plain-language things that went *right*
    * ``warnings``           caveats the homeowner / estimator should see

The inputs are the signals the measurement + recovery pipeline already
produces: ``recovery_status`` (the per-facet QA verdict, e.g. ``"ok:6"`` /
``"review:4"`` / ``"low_confidence:2"`` / ``"no_polygons"``), the roof's
``min_confidence`` and ``facets_needing_qa``, structure complexity, and whether
we recovered real line geometry at all.

We deliberately never fabricate confidence: a demo/fallback report or a roof
with no recovered geometry comes back *low*, with a warning saying so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# Band -> (starting confidence midpoint, price margin of error).
_BAND_DEFAULTS = {
    "high": (92, 0.08),
    "medium": (76, 0.15),
    "low": (52, 0.25),
}


@dataclass(frozen=True)
class Confidence:
    confidence_pct: int
    band: str
    margin_of_error_pct: float
    reasons: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()

    @property
    def score(self) -> float:
        """Engineering confidence as a 0-1 float (for internal storage/admin)."""
        return round(self.confidence_pct / 100.0, 2)

    def to_dict(self) -> dict:
        return {
            "confidence_pct": self.confidence_pct,
            "band": self.band,
            "margin_of_error_pct": round(self.margin_of_error_pct * 100),
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
        }


def _parse_status(recovery_status: Optional[str]) -> Tuple[str, int]:
    """Split ``"ok:6"`` -> ``("ok", 6)``. Bare statuses -> count 0."""
    if not recovery_status:
        return ("none", 0)
    m = re.match(r"([a-z_]+)(?::(\d+))?", str(recovery_status))
    if not m:
        return ("none", 0)
    return (m.group(1), int(m.group(2)) if m.group(2) else 0)


def assess(report: Dict[str, Any]) -> Confidence:
    """Assess confidence in a measurement report (the dict from
    :func:`roofwall.app.measure_address`)."""
    roof = report.get("roof") or {}
    recovery_status = report.get("recovery_status")
    status, status_count = _parse_status(recovery_status)
    is_demo = report.get("mode") == "demo" or bool(report.get("demo_reason"))
    has_lines = bool(report.get("line_lengths"))

    facet_count = int(roof.get("facet_count") or len(report.get("facets") or []))
    needs_qa = int(roof.get("facets_needing_qa") or 0)
    min_conf = roof.get("min_confidence")
    complexity = roof.get("structure_complexity")

    reasons: List[str] = []
    warnings: List[str] = []

    # 1) Base band from the recovery QA verdict.
    if is_demo:
        band = "low"
        warnings.append(
            "This is a sample estimate — connect live imagery for a measured quote."
        )
    elif status == "ok":
        band = "high"
        reasons.append("Roof geometry recovered cleanly from satellite imagery.")
    elif status == "review":
        band = "medium"
        warnings.append("Some roof facets need a quick manual review.")
    elif status == "low_confidence":
        band = "low"
        warnings.append("Imagery was noisy — measurements are approximate.")
    elif status in ("no_polygons", "none") or not has_lines:
        band = "low"
        warnings.append(
            "We couldn't trace exact roof lines — this estimate is based on the "
            "roof footprint and may shift after inspection."
        )
    else:
        band = "medium"

    pct, margin = _BAND_DEFAULTS[band]

    # 2) Nudge the score by per-facet QA signal.
    if facet_count > 0 and needs_qa:
        ratio = needs_qa / facet_count
        pct -= int(round(ratio * 20))
        warnings.append(
            f"{needs_qa} of {facet_count} roof faces flagged for manual review."
        )
    elif facet_count > 0 and band == "high":
        reasons.append(f"All {facet_count} roof faces measured with high confidence.")

    if isinstance(min_conf, (int, float)):
        if min_conf >= 0.85:
            pct += 2
        elif min_conf < 0.5:
            pct -= 6

    # 3) Complexity caveat (doesn't lower the score much, but worth flagging).
    if complexity == "Complex":
        warnings.append(
            "Complex roof — final price depends on access, layers and penetrations."
        )
        if band == "high":
            pct -= 3
    elif complexity == "Simple" and band == "high":
        reasons.append("Simple, regular roof shape — straightforward to estimate.")

    if has_lines and not is_demo:
        reasons.append("Ridge, hip, valley and eave lines were measured directly.")

    pct = max(35, min(99, pct))
    # Widen the price margin a touch for sparse roofs we have little to lean on.
    if facet_count and facet_count < 2:
        margin = min(0.30, margin + 0.05)

    return Confidence(
        confidence_pct=pct,
        band=band,
        margin_of_error_pct=margin,
        reasons=tuple(reasons),
        warnings=tuple(warnings),
    )

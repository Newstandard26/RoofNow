"""EagleView-style report sections computed from a RoofReport.

Deterministic, dependency-free aggregations that mirror an EagleView Premium
report: standard-pitch normalisation, predominant pitch by area, areas-per-pitch,
the waste-factor table, and a structure-complexity rating. These are pure
functions of the measured facets (no DSM needed), so they're fully unit-tested
against the 8656 Scott Lane benchmark.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

from roofwall.measurement.engine import ROOFING_SQUARE_SQFT, FacetMeasurement

# Waste percentages EagleView tabulates; "suggested" is chosen by complexity.
WASTE_STEPS = (0, 6, 11, 16, 19, 21, 23, 26, 31)


def snap_pitch_x12(x12: float) -> int:
    """Snap a rise-per-12 to the nearest standard integer pitch (6.4 -> 6)."""
    return max(0, int(round(x12)))


def standard_pitch_label(x12: float) -> str:
    return f"{snap_pitch_x12(x12)}/12"


def areas_per_pitch(facets: Sequence[FacetMeasurement]) -> list[dict[str, Any]]:
    """Sloped area grouped by standard pitch, largest first, with % of roof."""
    buckets: dict[int, float] = {}
    for f in facets:
        key = snap_pitch_x12(f.pitch.x12)
        buckets[key] = buckets.get(key, 0.0) + f.sloped_area_sqft
    total = sum(buckets.values()) or 1.0
    return [
        {"pitch": f"{x}/12",
         "area_sqft": round(buckets[x], 1),
         "percent": round(100.0 * buckets[x] / total, 1)}
        for x in sorted(buckets, key=lambda k: buckets[k], reverse=True)
    ]


def predominant_pitch(facets: Sequence[FacetMeasurement]) -> str | None:
    """Standard pitch bin holding the most sloped area (EagleView convention)."""
    rows = areas_per_pitch(facets)
    return rows[0]["pitch"] if rows else None


def round_up_third(squares: float) -> float:
    """Round squares UP to the nearest 1/3 square (EagleView ordering)."""
    return math.ceil(squares * 3 - 1e-9) / 3.0


def waste_table(total_sloped_sqft: float, suggested_pct: int) -> list[dict[str, Any]]:
    rows = []
    for p in WASTE_STEPS:
        area = total_sloped_sqft * (1.0 + p / 100.0)
        sq = round_up_third(area / ROOFING_SQUARE_SQFT)
        rows.append({"waste_pct": p, "area_sqft": round(area),
                     "squares": round(sq, 2), "suggested": p == suggested_pct})
    return rows


def structure_complexity(facet_count: int, valley_ft: float) -> str:
    """Simple / Normal / Complex from facet count + valley footage."""
    if facet_count <= 4 and valley_ft < 1.0:
        return "Simple"
    if facet_count >= 15 or valley_ft > 150.0:
        return "Complex"
    return "Normal"


_SUGGESTED_WASTE = {"Simple": 11, "Normal": 21, "Complex": 26}


def suggested_waste_pct(complexity: str) -> int:
    return _SUGGESTED_WASTE.get(complexity, 21)


def eagleview_sections(facets: Sequence[FacetMeasurement], total_sloped_sqft: float,
                       line_lengths: dict[str, Any] | None = None) -> dict[str, Any]:
    """Assemble the EagleView report add-ons as a JSON-able dict."""
    valley_ft = float(((line_lengths or {}).get("valley") or {}).get("length_ft", 0.0))
    complexity = structure_complexity(len(facets), valley_ft)
    suggested = suggested_waste_pct(complexity)
    return {
        "predominant_pitch": predominant_pitch(facets),
        "areas_per_pitch": areas_per_pitch(facets),
        "structure_complexity": complexity,
        "suggested_waste_pct": suggested,
        "waste_table": waste_table(total_sloped_sqft, suggested),
    }

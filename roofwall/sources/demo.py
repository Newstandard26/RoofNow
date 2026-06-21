"""Deterministic demo roofs — a working report with no API key.

Given an address, pick one of a few realistic roof archetypes (seeded by a
hash of the address so the same address always yields the same roof) and run
it through the real measurement engine + wall derivation. This powers the
hosted demo so the product is usable end-to-end; setting GOOGLE_MAPS_API_KEY
switches the app to live Google Solar data (see :mod:`roofwall.app`).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from roofwall.measurement.edges import gable_roof, hip_roof, line_lengths_dict
from roofwall.measurement.engine import (
    Pitch,
    measure_facet,
    summarize_roof,
)
from roofwall.report.render import report_to_dict
from roofwall.walls.height import elevation_breakdown


@dataclass(frozen=True)
class Archetype:
    name: str
    length_ft: float          # footprint dimension, E-W
    width_ft: float           # footprint dimension, N-S
    eave_height_ft: float
    # facets as (rise_over_12, azimuth_deg, plan_area_fraction)
    facets: tuple[tuple[float, float, float], ...]
    # gable triangles as (width_ft_factor_of_width, rise_over_12); width is
    # taken as the footprint width and rise derived from pitch.
    gable_count: int
    gable_pitch: float
    # openings as (width_ft, height_ft, kind, count)
    openings: tuple[tuple[float, float, str, int], ...]
    # 3D roof model used for the Length Diagram: "gable" | "hip"
    roof3d: str


ARCHETYPES: tuple[Archetype, ...] = (
    Archetype(
        name="Simple gable",
        length_ft=48.0,
        width_ft=30.0,
        eave_height_ft=10.0,
        facets=((6, 0, 0.5), (6, 180, 0.5)),
        gable_count=2,
        gable_pitch=6,
        openings=((3, 4, "window", 8), (3, 7, "door", 1), (16, 7, "garage", 1)),
        roof3d="gable",
    ),
    Archetype(
        name="Hip roof",
        length_ft=44.0,
        width_ft=32.0,
        eave_height_ft=10.0,
        facets=((5, 0, 0.30), (5, 180, 0.30), (5, 90, 0.20), (5, 270, 0.20)),
        gable_count=0,
        gable_pitch=5,
        openings=((3, 4, "window", 10), (3, 7, "door", 1), (9, 7, "garage", 1)),
        roof3d="hip",
    ),
    Archetype(
        name="Complex / cross-gable",
        length_ft=52.0,
        width_ft=38.0,
        eave_height_ft=11.0,
        facets=(
            (7, 0, 0.22), (7, 180, 0.22),
            (6, 90, 0.18), (6, 270, 0.18),
            (8, 45, 0.10), (8, 225, 0.10),
        ),
        gable_count=3,
        gable_pitch=7,
        openings=((3, 4, "window", 12), (3, 7, "door", 2), (16, 7, "garage", 1)),
        roof3d="hip",
    ),
)


def _roof3d_model(arch: Archetype, length: float, width: float):
    """Build a 3D facet model for the archetype's Length Diagram."""
    if arch.roof3d == "gable":
        return gable_roof(length, width, arch.gable_pitch)
    return hip_roof(length, width, arch.gable_pitch)


def _seed(address: str) -> int:
    key = (address or "demo").strip().lower()
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest(), 16)


def _gable_height(width_ft: float, rise_over_12: float) -> float:
    """Ridge height above the eave for a symmetric gable of this pitch."""
    return (width_ft / 2.0) * (rise_over_12 / 12.0)


def demo_full_report(address: str, *, waste_pct: float | None = None) -> dict[str, Any]:
    """Build a full roof + wall report dict for a demo address."""
    seed = _seed(address)
    arch = ARCHETYPES[seed % len(ARCHETYPES)]
    # Deterministic size variation, 0.85x .. 1.14x.
    scale = 0.85 + (seed % 30) / 100.0
    length = arch.length_ft * scale
    width = arch.width_ft * scale
    footprint_area = length * width

    # --- Roof ---------------------------------------------------------
    facets = [
        measure_facet(
            footprint_area_sqft=footprint_area * frac,
            pitch=Pitch.from_x12(rise),
            azimuth_deg=az,
            confidence=0.92,
            source="demo",
        )
        for rise, az, frac in arch.facets
    ]
    report = summarize_roof(facets, waste_pct=waste_pct)
    roof_dict = report_to_dict(report)

    # --- Walls --------------------------------------------------------
    ring = [(0.0, 0.0), (length, 0.0), (length, width), (0.0, width)]
    gables = [
        (width, _gable_height(width, arch.gable_pitch))
        for _ in range(arch.gable_count)
    ]
    bd = elevation_breakdown(ring, arch.eave_height_ft, gables=gables)
    opening_areas = [w * h * n for (w, h, _kind, n) in arch.openings]
    net = bd.net_siding_area(opening_areas, waste_pct=0.10)

    walls = {
        "eave_height_ft": round(arch.eave_height_ft, 1),
        "footprint_ft": {"length": round(length, 1), "width": round(width, 1)},
        "by_direction_sqft": {k: round(v) for k, v in bd.by_direction.items()},
        "gable_area_sqft": round(bd.gable_area),
        "gross_wall_area_sqft": round(bd.gross_wall_area),
        "openings_sqft": round(sum(opening_areas)),
        "net_siding_area_sqft": round(net),
        "openings": [
            {"width_ft": w, "height_ft": h, "kind": kind, "count": n}
            for (w, h, kind, n) in arch.openings
        ],
    }

    # --- Length Diagram (ridge/hip/valley/eave/rake) ------------------
    line_lengths = line_lengths_dict(_roof3d_model(arch, length, width))

    return {
        "mode": "demo",
        "address": address,
        "archetype": arch.name,
        "roof": roof_dict["roof"],
        "facets": roof_dict["facets"],
        "walls": walls,
        "line_lengths": line_lengths,
    }

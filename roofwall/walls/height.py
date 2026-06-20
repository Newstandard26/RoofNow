"""Wall heights & per-elevation areas (Phase 2).

Building height = DSM (eave/roof) - DTM (ground):
  * DSM: Solar API ``dataLayers`` GeoTIFF, or 3DEP first-return.
  * DTM: 3DEP bare-earth, or the footprint-perimeter minimum as a fallback.

Given a footprint and an eave height this module produces the gross wall
area and a North/South/East/West elevation breakdown — the input to the
engine's ``net_siding_area`` (openings subtracted in ``walls.openings``).

Geometry here is pure stdlib (no numpy); raster sampling for the DSM/DTM is
the only part that needs gdal and is stubbed at the bottom.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from roofwall.measurement.engine import gable_triangle_area, net_siding_area
from roofwall.measurement.geometry import Point, bearing_degrees, distance

# 4-point compass sectors, centered on each cardinal direction.
_CARDINALS = ["N", "E", "S", "W"]


def building_height(roof_or_dsm: float, ground_or_dtm: float) -> float:
    """Eave/building height = DSM - DTM. Clamped at zero."""
    return max(0.0, roof_or_dsm - ground_or_dtm)


def bearing_to_cardinal4(bearing_deg: float) -> str:
    """Map a bearing to one of N/E/S/W (nearest, 90° sectors)."""
    idx = int(((bearing_deg % 360.0) + 45.0) // 90.0) % 4
    return _CARDINALS[idx]


def wall_normal_cardinal(a: Point, b: Point) -> str:
    """Outward-facing cardinal of the wall segment a->b.

    Assumes the footprint is wound counter-clockwise, so the outward normal
    is 90° clockwise from the edge direction.
    """
    edge_bearing = bearing_degrees(a, b)
    outward = (edge_bearing + 90.0) % 360.0
    return bearing_to_cardinal4(outward)


@dataclass
class WallBreakdown:
    """Gross wall area split by elevation, plus any gable triangles."""

    height: float
    by_direction: dict[str, float] = field(default_factory=dict)
    gable_area: float = 0.0

    @property
    def gross_wall_area(self) -> float:
        return sum(self.by_direction.values()) + self.gable_area

    def net_siding_area(
        self, openings: Sequence[float] = (), waste_pct: float = 0.10
    ) -> float:
        return net_siding_area(self.gross_wall_area, openings, waste_pct)


def elevation_breakdown(
    footprint: Sequence[Point],
    height: float,
    *,
    gables: Sequence[tuple[float, float]] = (),
) -> WallBreakdown:
    """Per-elevation gross wall area for a footprint at a given eave height.

    ``footprint`` is a projected polygon ring (feet/meters, CCW). ``gables``
    is an optional list of ``(width, rise)`` gable triangles to add.
    """
    if height < 0:
        raise ValueError("height must be non-negative")
    ring = list(footprint)
    if len(ring) >= 2 and ring[0] == ring[-1]:
        ring = ring[:-1]
    if len(ring) < 3:
        raise ValueError("footprint needs >= 3 distinct vertices")

    by_dir: dict[str, float] = {c: 0.0 for c in _CARDINALS}
    n = len(ring)
    for i in range(n):
        a, b = ring[i], ring[(i + 1) % n]
        seg_len = distance(a, b)
        by_dir[wall_normal_cardinal(a, b)] += seg_len * height

    gable_area = sum(gable_triangle_area(w, h) for w, h in gables)
    return WallBreakdown(height=height, by_direction=by_dir, gable_area=gable_area)


# --------------------------------------------------------------------------
# Raster height sampling (optional — needs gdal/rasterio)
# --------------------------------------------------------------------------


def eave_height_from_rasters(
    footprint: Sequence[Point], dsm_path: str, dtm_path: str | None = None
) -> float:
    """Mean eave height over the footprint by sampling DSM/DTM rasters."""
    raise NotImplementedError(
        "DSM/DTM raster sampling needs gdal/rasterio; building_height() and "
        "elevation_breakdown() are the tested core."
    )

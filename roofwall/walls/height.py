"""Building / eave height from elevation rasters (Phase 2).

height = DSM (eave/roof) - DTM (ground)
  * DSM: Solar API ``dataLayers`` GeoTIFF, or 3DEP first-return.
  * DTM: 3DEP bare-earth, or footprint-perimeter minimum as a fallback.

Feeds ``gross_wall_area`` / ``gable_triangle_area`` in the engine.
"""

from __future__ import annotations

from typing import Sequence

from roofwall.measurement.geometry import Point


def eave_height_from_dsm_dtm(
    footprint: Sequence[Point],
    dsm_path: str,
    dtm_path: str | None = None,
) -> float:
    """Mean eave height (ft) over the footprint perimeter. (Phase 2.)"""
    raise NotImplementedError(
        "Height extraction is Phase 2 (DSM-DTM raster sampling)."
    )

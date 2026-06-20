"""USGS 3DEP LiDAR roof-plane pipeline (Phase 2 — not yet implemented).

Plan (per spec):
  1. Get footprint polygon (MS/Google footprints or Solar mask).
  2. ``pdal`` pipeline: read 3DEP EPT, crop to footprint+buffer, classify,
     compute normals.
  3. Segment planar patches: RANSAC (``open3d.geometry.segment_plane``) or
     region-growing on normals; merge co-planar patches.
  4. Per plane: area (project to plane), pitch = angle(normal, vertical),
     azimuth = heading of downslope direction.
  5. Reconstruct edges -> classify ridge/hip/valley/eave/rake from plane
     adjacency & orientation; compute lengths.

This is the free, no-resale-restriction margin play and the Solar API
coverage-gap fallback. Output must be ``list[FacetMeasurement]`` so it
feeds the same engine as the Solar path.
"""

from __future__ import annotations

from typing import Sequence

from roofwall.measurement.engine import FacetMeasurement
from roofwall.measurement.geometry import Point

# Public-domain 3DEP entwine point tiles on AWS.
EPT_3DEP_RESOURCE = "https://s3-us-west-2.amazonaws.com/usgs-lidar-public/"


def roof_facets_from_lidar(
    footprint: Sequence[Point],
    *,
    buffer_m: float = 2.0,
) -> list[FacetMeasurement]:
    """Fit roof planes from 3DEP LiDAR within a footprint. (Phase 2.)"""
    raise NotImplementedError(
        "LiDAR plane-fit pipeline is Phase 2; see module docstring for steps."
    )

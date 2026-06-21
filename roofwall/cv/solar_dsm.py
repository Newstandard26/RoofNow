"""Approach A — Solar DSM raster -> planes -> facet polygons (BuildingModel).

Reuses Google Solar as **plane priors**: each ``roofSegmentStats`` entry gives
a plane (pitch / azimuth / height) and the DSM gives per-pixel heights, so we
label pixels by nearest plane, trace + regularize each region's boundary, lift
to 3D, then weld shared edges.

What's implemented here (pure Python, tested):
  * :func:`plane_from_segment` — Solar segment -> plane ``z = a*x + b*y + c``
    in the local ENU (feet) frame.
  * :func:`lift` — recover a vertex's z from its plane.

What's stubbed (needs rasterio / scikit-image / scipy / shapely + live signed
DSM downloads, which exceed this environment): pulling Data Layers, cropping to
the mask, assigning pixels to planes, and contour tracing / regularization.
These raise ``NotImplementedError`` — they are NOT faked (per the spec: don't
fabricate line lengths when the data isn't there).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, List, Optional

from roofwall.measurement.edges import Vec
from roofwall.measurement.engine import M_TO_FT
from roofwall.model import BuildingModel, Origin

# Solar Data Layers DSM resolution.
DSM_RES_M = 0.1


@dataclass(frozen=True)
class Plane:
    """z = a*x + b*y + c, in local ENU feet."""

    a: float
    b: float
    c: float

    def z_at(self, x: float, y: float) -> float:
        return self.a * x + self.b * y + self.c


def plane_from_segment(
    pitch_deg: float,
    azimuth_deg: float,
    center_xy_ft: tuple[float, float],
    height_ft: float,
) -> Plane:
    """Plane for a Solar roof segment in the local ENU (feet) frame.

    ``azimuth_deg`` is the downslope/facing heading (0=N, clockwise), matching
    the engine convention. The plane descends along that compass direction at
    the segment's slope, passing through ``(center, height)``.
    """
    slope = math.tan(math.radians(pitch_deg))  # rise/run
    az = math.radians(azimuth_deg)
    # Downslope horizontal unit vector (x=E, y=N): (sin az, cos az).
    # z decreases along it, so the gradient is -slope * that vector.
    a = -slope * math.sin(az)
    b = -slope * math.cos(az)
    cx, cy = center_xy_ft
    c = height_ft - a * cx - b * cy
    return Plane(a=a, b=b, c=c)


def lift(x: float, y: float, plane: Plane) -> Vec:
    """Lift a 2D vertex to 3D using its plane equation."""
    return (x, y, plane.z_at(x, y))


def lift_polygon(xy: List[tuple[float, float]], plane: Plane) -> List[Vec]:
    return [lift(x, y, plane) for x, y in xy]


def planes_from_building_insights(
    payload: dict[str, Any], origin_latlng: tuple[float, float]
) -> list[Plane]:
    """Build a plane per Solar roof segment (centers placed in a local frame).

    Segment centers come back as lat/lng; we project them to a local ENU frame
    in feet using an equirectangular approximation about ``origin_latlng``.
    """
    olat, olng = origin_latlng
    cos_lat = math.cos(math.radians(olat))
    planes: list[Plane] = []
    for seg in (payload.get("solarPotential") or {}).get("roofSegmentStats") or []:
        center = seg.get("center") or {}
        clat = center.get("latitude", olat)
        clng = center.get("longitude", olng)
        # meters east/north -> feet
        east_ft = math.radians(clng - olng) * 6378137.0 * cos_lat * M_TO_FT
        north_ft = math.radians(clat - olat) * 6378137.0 * M_TO_FT
        height_ft = float(seg.get("planeHeightAtCenterMeters", 0.0)) * M_TO_FT
        planes.append(
            plane_from_segment(
                float(seg.get("pitchDegrees", 0.0)),
                float(seg.get("azimuthDegrees", 0.0)),
                (east_ft, north_ft),
                height_ft,
            )
        )
    return planes


# --------------------------------------------------------------------------
# Live DSM download — the only remaining stub. The recovery core (pixel
# labeling, tracing, regularization, lifting, snapping) lives in recover.py
# and is validated by the synthetic round-trip test.
# --------------------------------------------------------------------------

_RASTER_HINT = (
    "requires rasterio + the API key and live signed Solar Data Layer URLs "
    "(which expire ~1h); run where those are available (or a separate Cloud "
    "Run service) per spec approach A. Not faked."
)


def priors_from_building_insights(
    payload: dict[str, Any], origin_latlng: tuple[float, float]
) -> list[dict[str, Any]]:
    """``recover()`` priors ``[{"id", "abc"}]`` from Solar segments (local feet)."""
    return [
        {"id": f"seg{i}", "abc": (p.a, p.b, p.c)}
        for i, p in enumerate(planes_from_building_insights(payload, origin_latlng))
    ]


def build_model_from_dsm(
    dsm, mask, transform, priors, origin: Origin, *, notes: Optional[str] = None
) -> BuildingModel:
    """Recover facet polygons from a DSM (recover()) and wrap as a BuildingModel."""
    from roofwall.cv.recover import recover  # lazy: pulls skimage/shapely
    from roofwall.measurement.snapping import to_roof_edges

    facets = recover(dsm, mask, transform, priors)
    return BuildingModel.from_edge_facets(
        to_roof_edges(facets), origin, "solar-dsm", notes
    )


def _download_data_layers(lat: float, lng: float, key: str) -> Any:  # pragma: no cover
    raise NotImplementedError(
        "Solar dataLayers:get download + GeoTIFF read " + _RASTER_HINT
    )


def build_model_from_solar_dsm(
    lat: float, lng: float, key: str, *, notes: Optional[str] = None
) -> BuildingModel:
    """Full approach-A pipeline.

    The recovery core (``recover()`` — pixel labeling, contour tracing,
    regularization, lifting, snapping) is implemented and tested via the
    synthetic round-trip. Only the live signed-DSM **download** remains
    (needs rasterio + the API key), so this raises there — not faked.
    """
    dsm, mask, transform = _download_data_layers(lat, lng, key)  # stub raises here
    from roofwall.sources.solar import SolarClient

    payload = SolarClient(api_key=key).building_insights(lat, lng)
    priors = priors_from_building_insights(payload, (lat, lng))
    return build_model_from_dsm(dsm, mask, transform, priors, Origin(lat, lng), notes=notes)

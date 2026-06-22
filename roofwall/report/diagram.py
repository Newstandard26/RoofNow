"""Top-down roof diagram data — per-facet polygons for the UI to draw.

Two sources, both produce ``[{poly, pitch, azimuth_deg, facing, area_sqft}]``
in a local feet frame (x=East, y=North), ready for an SVG:

  * :func:`from_solar` — live Google Solar segments (each segment's
    ``boundingBox`` projected to feet). Axis-aligned boxes, colored by
    orientation: a real schematic of the roof's facets without needing the
    DSM-recovery polygons.
  * :func:`from_edge_facets` — true facet polygons (demo 3D model / LiDAR),
    projected to the x-y plane.
"""

from __future__ import annotations

import math
from typing import Any

from roofwall.measurement.engine import M_TO_FT, Pitch, sqm_to_sqft
from roofwall.report.render import azimuth_to_cardinal

_R = 6378137.0  # WGS84 mean radius (m)


def _project(lat: float, lng: float, olat: float, olng: float) -> list[float]:
    x = math.radians(lng - olng) * math.cos(math.radians(olat)) * _R * M_TO_FT
    y = math.radians(lat - olat) * _R * M_TO_FT
    return [round(x, 2), round(y, 2)]


def from_solar(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Facet rectangles from Solar ``roofSegmentStats[].boundingBox``."""
    solar = payload.get("solarPotential") or {}
    segments = solar.get("roofSegmentStats") or []
    center = payload.get("center") or {}
    olat, olng = center.get("latitude"), center.get("longitude")
    if olat is None or olng is None:
        cs = [s.get("center") or {} for s in segments]
        lats = [c["latitude"] for c in cs if "latitude" in c]
        lngs = [c["longitude"] for c in cs if "longitude" in c]
        if not lats:
            return []
        olat, olng = sum(lats) / len(lats), sum(lngs) / len(lngs)

    out: list[dict[str, Any]] = []
    for s in segments:
        bb = s.get("boundingBox") or {}
        sw, ne = bb.get("sw") or {}, bb.get("ne") or {}
        if "latitude" not in sw or "latitude" not in ne:
            continue
        x0, y0 = _project(sw["latitude"], sw["longitude"], olat, olng)
        x1, y1 = _project(ne["latitude"], ne["longitude"], olat, olng)
        az = float(s.get("azimuthDegrees", 0.0))
        deg = min(float(s.get("pitchDegrees", 0.0)), 89.9)
        area = sqm_to_sqft(float((s.get("stats") or {}).get("areaMeters2", 0.0)))
        out.append({
            "poly": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
            "pitch": Pitch.from_degrees(deg).label(),
            "azimuth_deg": round(az, 1),
            "facing": azimuth_to_cardinal(az),
            "area_sqft": round(area, 1),
        })
    return out


def from_edge_facets(facets) -> list[dict[str, Any]]:
    """Facet polygons from 3D EdgeFacets, projected to the x-y plane."""
    out: list[dict[str, Any]] = []
    for f in facets:
        out.append({
            "poly": [[round(v[0], 2), round(v[1], 2)] for v in f.verts],
            "pitch": f.pitch.label(),
            "azimuth_deg": round(f.azimuth_deg, 1),
            "facing": azimuth_to_cardinal(f.azimuth_deg),
            "area_sqft": None,
        })
    return out

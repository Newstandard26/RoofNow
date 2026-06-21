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
import os
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
    "requires the API key and live signed Solar Data Layer URLs (which expire "
    "~1h) to download the DSM + mask GeoTIFFs; everything after the download "
    "(geo CRS->feet, recover, snapping) is implemented and tested. Run where "
    "outbound fetches + the key are available (or a separate Cloud Run "
    "service) per spec approach A. Not faked."
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


def geo_segments(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Solar ``roofSegmentStats`` -> ``geo.priors_from_solar`` segment dicts."""
    out: list[dict[str, Any]] = []
    for i, seg in enumerate((payload.get("solarPotential") or {}).get("roofSegmentStats") or []):
        center = seg.get("center") or {}
        out.append({
            "id": f"seg{i}",
            "pitch_degrees": float(seg.get("pitchDegrees", 0.0)),
            "azimuth_degrees": float(seg.get("azimuthDegrees", 0.0)),
            "center": {"latitude": center.get("latitude"),
                       "longitude": center.get("longitude")},
            "plane_height_m": float(seg.get("planeHeightAtCenterMeters", 0.0)),
        })
    return out


def build_model_from_geotiffs(
    dsm_path: str, mask_path: str, segments: list[dict[str, Any]],
    origin: Origin, *, notes: Optional[str] = None
) -> BuildingModel:
    """DSM + building-mask GeoTIFFs (any projected CRS) + Solar segments -> BuildingModel.

    ``geo.geotiff_to_local`` handles the CRS -> local-feet conversion (the
    sec(latitude) correction), so segment priors land in the same frame as the
    raster. The only remaining live step is downloading the two GeoTIFFs.
    """
    import rasterio  # lazy: pulls GDAL

    from roofwall.cv.geo import geotiff_to_local, priors_from_solar

    dsm_ft, transform, lonlat_to_local, meta = geotiff_to_local(dsm_path, to_feet=True)
    with rasterio.open(mask_path) as ds:
        mask = (ds.read(1) > 0).astype("uint8")
    priors = priors_from_solar(segments, lonlat_to_local)
    if meta.get("rotation_warn") and not notes:
        notes = "raster grid is rotated >1deg from N/E; lengths may be approximate"
    return build_model_from_dsm(dsm_ft, mask, transform, priors, origin, notes=notes)


def _fetch_signed(url: str, key: str) -> bytes:
    """GET a Solar signed Data-Layer URL (key appended) and return the bytes."""
    import requests

    resp = requests.get(url, params={"key": key}, timeout=60)
    resp.raise_for_status()
    return resp.content


def _download_data_layers(
    lat: float, lng: float, key: str, *,
    radius_m: float = 50.0, client: Any = None, fetch: Any = None
) -> tuple[str, str]:
    """Fetch Solar ``dataLayers:get`` and download the signed DSM + mask GeoTIFFs.

    Returns ``(dsm_path, mask_path)`` (temp files). Signed URLs expire ~1h, so we
    download immediately. ``client``/``fetch`` are injectable for tests.
    """
    import tempfile

    from roofwall.sources.solar import SolarClient

    client = client or SolarClient(api_key=key)
    fetch = fetch or _fetch_signed
    layers = client.data_layers(lat, lng, radius_m)
    dsm_url, mask_url = layers.get("dsmUrl"), layers.get("maskUrl")
    if not dsm_url or not mask_url:
        raise RuntimeError("dataLayers response missing dsmUrl/maskUrl")

    d = tempfile.mkdtemp(prefix="roofwall_dsm_")
    dsm_path = os.path.join(d, "dsm.tif")
    mask_path = os.path.join(d, "mask.tif")
    with open(dsm_path, "wb") as f:
        f.write(fetch(dsm_url, key))
    with open(mask_path, "wb") as f:
        f.write(fetch(mask_url, key))
    return dsm_path, mask_path


def build_model_from_solar_dsm(
    lat: float, lng: float, key: str, *, notes: Optional[str] = None,
    client: Any = None, fetch: Any = None
) -> BuildingModel:
    """Full approach-A pipeline: Solar segments + DSM -> facet polygons.

    Implemented end to end (segment planes, CRS->feet, download, pixel labeling
    + tracing + snapping). Needs the geospatial deps (~400 MB) + key + outbound
    network, so it runs in the roofwall-cv service, not the Vercel function.
    ``client``/``fetch`` are injectable for offline testing.
    """
    from roofwall.sources.solar import SolarClient

    client = client or SolarClient(api_key=key)
    payload = client.building_insights(lat, lng)
    segments = geo_segments(payload)
    dsm_path, mask_path = _download_data_layers(
        lat, lng, key, client=client, fetch=fetch
    )
    return build_model_from_geotiffs(
        dsm_path, mask_path, segments, Origin(lat, lng), notes=notes
    )

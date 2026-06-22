"""Lightweight DSM -> facet-polygon recovery that fits a Vercel function.

Same algorithm as recover.py + geo.py, but with the heavy geospatial stack
(rasterio/GDAL, scikit-image/scipy, shapely, pyproj ~400 MB) swapped for a
~74 MB set: numpy + tifffile (read the GeoTIFF) + contourpy (trace facet
boundaries). The plane fitting (assign_pixels), shared-edge snapping and edge
classification are reused unchanged.

CRS note: assumes the Solar Data-Layer DSM/mask are EPSG:3857 (Web Mercator),
the common case; georeferencing uses the GeoTIFF ModelPixelScale/ModelTiepoint
tags + a closed-form Mercator inverse (no pyproj).
"""

from __future__ import annotations

import io
import math
from typing import Any, List, Optional

import numpy as np
import tifffile
from contourpy import contour_generator

from roofwall.cv.recover import (
    RasterTransform,
    assign_pixels,
    plane_from_solar_segment,
    plane_z,
)
from roofwall.measurement.engine import M_TO_FT
from roofwall.measurement.snapping import snap_model

_R = 6378137.0  # WGS84 / Web Mercator radius (m)


# ---------- GeoTIFF read + georeference (no rasterio/pyproj) ----------
# EPSG codes that are Web Mercator (the closed-form inverse below applies).
_WEBMERC_EPSG = {3857, 900913, 102100, 3587, 3785}


def _read_geotiff(data: bytes):
    """Return (array, sx, sy, ox, oy, epsg): pixel scales (world units/px) and
    the world coords of the top-left pixel corner (0, 0). Supports both standard
    GeoTIFF georeferencings — ModelPixelScale+ModelTiepoint and the
    ModelTransformation matrix — reading via parsed geokeys or raw tags. On
    failure raises with the tags actually present so the format is diagnosable.
    """
    with tifffile.TiffFile(io.BytesIO(data)) as tf:
        page = tf.pages[0]
        arr = page.asarray().astype(float)
        tags = page.tags
        try:
            geo = dict(page.geotiff_tags or {})
        except Exception:  # noqa: BLE001 - geokey parsing is best-effort
            geo = {}

        def tag_val(code: int, name: str):
            if geo.get(name) is not None:
                return geo[name]
            t = tags.get(code)
            return t.value if t is not None else None

        scale = tag_val(33550, "ModelPixelScale")
        tie = tag_val(33922, "ModelTiepoint")
        xform = tag_val(34264, "ModelTransformation")
        epsg = geo.get("ProjectedCSTypeGeoKey") or geo.get("GeographicTypeGeoKey")
        present = sorted({t.name for t in tags.values()} | set(geo.keys()))

    if scale is not None and tie is not None and len(scale) >= 2 and len(tie) >= 5:
        sx, sy = float(scale[0]), float(scale[1])
        ox = float(tie[3]) - float(tie[0]) * sx   # back out the tiepoint's pixel offset
        oy = float(tie[4]) + float(tie[1]) * sy
    elif xform is not None and len(xform) >= 8:
        m = [float(v) for v in xform]             # row-major 4x4
        sx, sy = m[0], -m[5]
        ox, oy = m[3], m[7]
    else:
        raise ValueError(
            "GeoTIFF georeference not found (no ModelPixelScale/ModelTiepoint or "
            "ModelTransformation); tags present: " + ", ".join(present))
    try:
        epsg = int(epsg) if epsg is not None else None
    except (TypeError, ValueError):
        epsg = None
    return arr, sx, sy, ox, oy, epsg


def _merc_to_lonlat(x: float, y: float) -> tuple[float, float]:
    return (math.degrees(x / _R),
            math.degrees(2.0 * math.atan(math.exp(y / _R)) - math.pi / 2.0))


def geotiff_to_local(data: bytes, *, to_feet: bool = True, ref_lonlat=None):
    """Read a 3857 GeoTIFF and return (array, RasterTransform[feet],
    lonlat_to_local[feet], meta). Mirrors geo.geotiff_to_local."""
    arr, sx, sy, ox, oy, epsg = _read_geotiff(data)
    if epsg is not None and epsg not in _WEBMERC_EPSG:
        raise ValueError(
            f"GeoTIFF CRS EPSG:{epsg} unsupported by the light reader "
            "(expects Web Mercator / EPSG:3857)")
    if to_feet:
        arr = arr * M_TO_FT
    nrows, ncols = arr.shape

    def px_lonlat(col: float, row: float):
        return _merc_to_lonlat(ox + (col + 0.5) * sx, oy - (row + 0.5) * sy)

    lon0, lat0 = ref_lonlat if ref_lonlat else px_lonlat(ncols / 2.0, nrows / 2.0)
    coslat = math.cos(math.radians(lat0))

    def lonlat_to_local(lon: float, lat: float):
        e = math.radians(lon - lon0) * coslat * _R * M_TO_FT
        n = math.radians(lat - lat0) * _R * M_TO_FT
        return (e, n)

    def loc(col: float, row: float):
        return lonlat_to_local(*px_lonlat(col, row))

    p00, p10, p01 = loc(0, nrows - 1), loc(1, nrows - 1), loc(0, nrows - 2)
    res = 0.5 * (math.hypot(p10[0] - p00[0], p10[1] - p00[1])
                 + math.hypot(p01[0] - p00[0], p01[1] - p00[1]))
    transform = RasterTransform(x0=p00[0], y0=p00[1], res=res, nrows=nrows)
    return arr, transform, lonlat_to_local, {"res_ft": res, "lon0": lon0, "lat0": lat0,
                                             "shape": (nrows, ncols)}


def priors_from_solar(segments: List[dict], lonlat_to_local) -> List[dict]:
    out = []
    for s in segments:
        x, y = lonlat_to_local(s["center"]["longitude"], s["center"]["latitude"])
        z = s["plane_height_m"] * M_TO_FT
        out.append({"id": str(s["id"]),
                    "abc": plane_from_solar_segment(s["pitch_degrees"],
                                                    s["azimuth_degrees"], (x, y, z))})
    return out


# ---------- contour trace + Douglas-Peucker (contourpy, no skimage/shapely) ----------
def _perp(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy)
    if L == 0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    return abs(dy * (p[0] - a[0]) - dx * (p[1] - a[1])) / L


def _dp(pts, eps):
    if len(pts) < 3:
        return pts
    dmax, idx = 0.0, 0
    for i in range(1, len(pts) - 1):
        d = _perp(pts[i], pts[0], pts[-1])
        if d > dmax:
            dmax, idx = d, i
    if dmax > eps:
        return _dp(pts[:idx + 1], eps)[:-1] + _dp(pts[idx:], eps)
    return [pts[0], pts[-1]]


def _trace_region(region: np.ndarray, plane, transform: RasterTransform, simplify_ft: float):
    if int(region.sum()) == 0:
        return []
    z = np.pad(region.astype(float), 1)
    lines = contour_generator(z=z).lines(0.5)
    if not lines:
        return []
    best = max(lines, key=len)  # (col, row) at pad+0.5 offset
    pts = [(float(x - 1), float(y - 1)) for x, y in best]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) < 3:
        return []
    eps = max(simplify_ft / max(transform.res, 1e-6), 0.5)
    simplified = _dp(pts + [pts[0]], eps)[:-1]
    if len(simplified) < 3:
        return []
    out = []
    for col, row in simplified:
        x, y = transform.colrow_to_world(col, row)
        out.append((x, y, plane_z(plane, x, y)))
    return out


def recover_light(dsm, mask, transform, priors, *, max_residual=2.0, simplify_ft=1.0,
                  snap_tol=1.2, edge_tol=0.9, min_facet_area_px=12):
    planes = [p["abc"] for p in priors]
    labels = assign_pixels(dsm, mask, planes, transform, max_residual)
    facets = []
    for i, prior in enumerate(priors):
        region = labels == i
        if int(region.sum()) < min_facet_area_px:
            continue
        verts = _trace_region(region, planes[i], transform, simplify_ft)
        if len(verts) >= 3:
            facets.append({"id": prior["id"], "verts": verts})
    return snap_model(facets, snap_tol=snap_tol, edge_tol=edge_tol)


# ---------- orchestrator ----------
def _fetch_bytes(url: str, key: str) -> bytes:
    import requests
    resp = requests.get(url, params={"key": key}, timeout=60)
    resp.raise_for_status()
    return resp.content


def build_model_light(lat: float, lng: float, key: str, *,
                      client: Any = None, fetch: Any = None):
    """Solar segments + DSM/mask GeoTIFFs -> BuildingModel, with light deps."""
    from roofwall.cv.solar_dsm import geo_segments
    from roofwall.measurement.snapping import to_roof_edges
    from roofwall.model import BuildingModel, Origin
    from roofwall.sources.solar import SolarClient

    client = client or SolarClient(api_key=key)
    fetch = fetch or _fetch_bytes
    payload = client.building_insights(lat, lng)
    segments = geo_segments(payload)

    layers = client.data_layers(lat, lng, 50.0)
    dsm_b = fetch(layers["dsmUrl"], key)
    mask_b = fetch(layers["maskUrl"], key)

    dsm_ft, transform, lonlat_to_local, meta = geotiff_to_local(dsm_b, to_feet=True)
    mask_arr, _, _, _ = geotiff_to_local(mask_b, to_feet=False, ref_lonlat=(meta["lon0"], meta["lat0"]))
    mask = (mask_arr > 0).astype("uint8")
    priors = priors_from_solar(segments, lonlat_to_local)
    facets = recover_light(dsm_ft, mask, transform, priors)
    return BuildingModel.from_edge_facets(to_roof_edges(facets), Origin(lat, lng), "solar-dsm")

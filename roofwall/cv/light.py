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

    # Values may arrive as flat tuples (raw tags) or numpy arrays of any shape
    # (parsed geokeys, e.g. ModelTransformation as a 4x4) — flatten before use.
    scale = np.asarray(scale, dtype=float).ravel() if scale is not None else None
    tie = np.asarray(tie, dtype=float).ravel() if tie is not None else None
    xform = np.asarray(xform, dtype=float).ravel() if xform is not None else None

    if scale is not None and tie is not None and scale.size >= 2 and tie.size >= 5:
        sx, sy = float(scale[0]), float(scale[1])
        ox = float(tie[3]) - float(tie[0]) * sx   # back out the tiepoint's pixel offset
        oy = float(tie[4]) + float(tie[1]) * sy
    elif xform is not None and xform.size >= 8:
        sx, sy = float(xform[0]), float(-xform[5])  # row-major 4x4 affine
        ox, oy = float(xform[3]), float(xform[7])
    else:
        raise ValueError(
            "GeoTIFF georeference not found (no ModelPixelScale/ModelTiepoint or "
            "ModelTransformation); tags present: " + ", ".join(present))
    return arr, sx, sy, ox, oy, _as_epsg(epsg)


def _as_epsg(v):
    """Coerce a geokey CRS value (int, str, or 1-element array) to int | None."""
    if v is None:
        return None
    try:
        return int(np.asarray(v).ravel()[0])
    except (TypeError, ValueError, IndexError):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None


def _merc_to_lonlat(x: float, y: float) -> tuple[float, float]:
    return (math.degrees(x / _R),
            math.degrees(2.0 * math.atan(math.exp(y / _R)) - math.pi / 2.0))


# WGS84 ellipsoid (for the UTM / Transverse-Mercator inverse).
_WGS_A = 6378137.0
_WGS_F = 1.0 / 298.257223563
_WGS_E2 = _WGS_F * (2.0 - _WGS_F)


def _utm_to_lonlat_factory(zone: int, northern: bool):
    """Closed-form inverse Transverse Mercator (Snyder) for a WGS84 UTM zone.
    Returns a function (easting, northing) -> (lon_deg, lat_deg). Pure Python,
    so the light stack stays free of pyproj/PROJ. Accurate to <1 m in-zone.
    """
    a, e2 = _WGS_A, _WGS_E2
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    ep2 = e2 / (1 - e2)
    k0 = 0.9996
    lon0 = math.radians(zone * 6 - 183)              # central meridian
    false_n = 0.0 if northern else 10_000_000.0
    m_denom = a * (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256)

    def to_lonlat(easting: float, northing: float):
        x = easting - 500_000.0
        mu = ((northing - false_n) / k0) / m_denom
        phi1 = (mu
                + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
                + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
                + (151 * e1**3 / 96) * math.sin(6 * mu)
                + (1097 * e1**4 / 512) * math.sin(8 * mu))
        s1, c1, t1 = math.sin(phi1), math.cos(phi1), math.tan(phi1)
        C1 = ep2 * c1**2
        T1 = t1**2
        N1 = a / math.sqrt(1 - e2 * s1**2)
        R1 = a * (1 - e2) / (1 - e2 * s1**2) ** 1.5
        D = x / (N1 * k0)
        phi = phi1 - (N1 * t1 / R1) * (
            D**2 / 2
            - (5 + 3 * T1 + 10 * C1 - 4 * C1**2 - 9 * ep2) * D**4 / 24
            + (61 + 90 * T1 + 298 * C1 + 45 * T1**2 - 252 * ep2 - 3 * C1**2) * D**6 / 720)
        lon = lon0 + (
            D
            - (1 + 2 * T1 + C1) * D**3 / 6
            + (5 - 2 * C1 + 28 * T1 - 3 * C1**2 + 8 * ep2 + 24 * T1**2) * D**5 / 120) / c1
        return (math.degrees(lon), math.degrees(phi))

    return to_lonlat


def _projector(epsg):
    """Pick a (world-x, world-y) -> (lon, lat) inverse for the GeoTIFF's CRS.
    Solar DSMs come in WGS84 UTM (EPSG 326xx N / 327xx S); also accept Web
    Mercator. Anything else raises with the EPSG so it's actionable.
    """
    if epsg is None or epsg in _WEBMERC_EPSG:
        return _merc_to_lonlat
    if 32601 <= epsg <= 32660:
        return _utm_to_lonlat_factory(epsg - 32600, northern=True)
    if 32701 <= epsg <= 32760:
        return _utm_to_lonlat_factory(epsg - 32700, northern=False)
    raise ValueError(
        f"GeoTIFF CRS EPSG:{epsg} unsupported by the light reader "
        "(supports Web Mercator / EPSG:3857 and WGS84 UTM / EPSG:326xx,327xx)")


def geotiff_to_local(data: bytes, *, to_feet: bool = True, ref_lonlat=None):
    """Read a Solar DSM/mask GeoTIFF (UTM or Web Mercator) and return
    (array, RasterTransform[feet], lonlat_to_local[feet], meta)."""
    arr, sx, sy, ox, oy, epsg = _read_geotiff(data)
    to_lonlat = _projector(epsg)
    if to_feet:
        arr = arr * M_TO_FT
    nrows, ncols = arr.shape

    def px_lonlat(col: float, row: float):
        return to_lonlat(ox + (col + 0.5) * sx, oy - (row + 0.5) * sy)

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


def _merge_priors(priors, *, slope_tol: float = 0.05, z_tol: float = 2.0):
    """Collapse Solar over-segmentation. Google's Solar API often splits one
    physical roof plane into several roofSegmentStats; each becomes a near-equal
    plane prior (a, b, c). With several near-duplicates, assign_pixels splits a
    single facet's pixels between them on noise alone, fragmenting it. Merge
    priors whose plane coefficients match within tolerance so each physical
    plane is one prior. a, b are slopes (tan pitch); c is the plane's height (ft)
    extrapolated to the local origin, so z_tol distinguishes stacked roofs.
    """
    merged: List[dict] = []
    for p in priors:
        a, b, c = p["abc"]
        for m in merged:
            ma, mb, mc = m["abc"]
            if (abs(a - ma) <= slope_tol and abs(b - mb) <= slope_tol
                    and abs(c - mc) <= z_tol):
                break
        else:
            merged.append({"id": p["id"], "abc": (a, b, c)})
    return merged


def _fit_plane(xs: np.ndarray, ys: np.ndarray, zs: np.ndarray):
    """Least-squares plane z = a*x + b*y + c through (xs, ys, zs) via the 3x3
    normal equations. Returns (a, b, c) or None if degenerate."""
    n = xs.size
    if n < 3:
        return None
    Sx, Sy, Sz = xs.sum(), ys.sum(), zs.sum()
    Sxx, Syy, Sxy = (xs * xs).sum(), (ys * ys).sum(), (xs * ys).sum()
    Sxz, Syz = (xs * zs).sum(), (ys * zs).sum()
    M = np.array([[Sxx, Sxy, Sx], [Sxy, Syy, Sy], [Sx, Sy, float(n)]])
    try:
        a, b, c = np.linalg.solve(M, np.array([Sxz, Syz, Sz]))
    except np.linalg.LinAlgError:
        return None
    return (float(a), float(b), float(c))


def _poly_area_sqft(verts) -> float:
    """Horizontal (x-y) polygon area by the shoelace formula."""
    n = len(verts)
    s = 0.0
    for i in range(n):
        x1, y1 = verts[i][0], verts[i][1]
        x2, y2 = verts[(i + 1) % n][0], verts[(i + 1) % n][1]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def recover_light(dsm, mask, transform, priors, *, max_residual=2.0, simplify_ft=1.8,
                  snap_tol=2.5, edge_tol=1.5, min_facet_area_px=24,
                  min_facet_area_sqft=25.0, min_keep_sqft=40.0, refine_iters=4):
    """DSM + Solar plane priors -> snapped facet polygons.

    The Solar priors are only an initialization: their pitch/azimuth/height are
    approximate, so a fixed plane only grazes the real roof in a thin band (the
    cause of the noodly, fragmented facets). We refine with a few EM passes —
    assign pixels to the nearest plane, refit each plane by least squares to its
    pixels, re-merge any planes that converge together — so the planes settle
    onto the true roof surfaces and each facet fills in as a compact region.
    Tracing then simplifies edges, drops speck facets (< min_facet_area_sqft),
    and welds shared edges (snap_tol) to close seams between neighbours.
    """
    priors = _merge_priors(priors)
    planes = [p["abc"] for p in priors]
    ids = [p["id"] for p in priors]
    nrows, ncols = dsm.shape
    Xg, Yg = transform.grids(ncols)

    for _ in range(max(0, refine_iters)):
        labels = assign_pixels(dsm, mask, planes, transform, max_residual)
        refit = []
        for i, pl in enumerate(planes):
            reg = labels == i
            fit = _fit_plane(Xg[reg], Yg[reg], dsm[reg]) if reg.any() else None
            refit.append(fit or pl)
        # Planes for one physical surface converge together — collapse them so
        # they don't re-fragment the facet on the next assignment.
        deduped = _merge_priors([{"id": ids[i], "abc": refit[i]}
                                 for i in range(len(refit))])
        new_planes = [d["abc"] for d in deduped]
        if new_planes == planes:
            break
        planes, ids = new_planes, [d["id"] for d in deduped]

    labels = assign_pixels(dsm, mask, planes, transform, max_residual)
    # Prune to the dominant planes: drop any plane that owns less than
    # min_keep_sqft of roof, then reassign every pixel to a surviving plane.
    # Noise bumps (vents, AC units, tree overhang) spawn tiny spurious planes;
    # left in, each adds phantom ridges/hips/valleys and chops the eave outline.
    res2 = transform.res * transform.res
    keep = [i for i in range(len(planes))
            if int((labels == i).sum()) * res2 >= min_keep_sqft]
    if keep and len(keep) < len(planes):
        planes = [planes[i] for i in keep]
        ids = [ids[i] for i in keep]
        labels = assign_pixels(dsm, mask, planes, transform, max_residual)

    facets = []
    for i, pid in enumerate(ids):
        region = labels == i
        if int(region.sum()) < min_facet_area_px:
            continue
        verts = _trace_region(region, planes[i], transform, simplify_ft)
        if len(verts) >= 3 and _poly_area_sqft(verts) >= min_facet_area_sqft:
            facets.append({"id": pid, "verts": verts})
    snapped = snap_model(facets, snap_tol=snap_tol, edge_tol=edge_tol)
    # Line lengths from the plane geometry (accurate even when facets don't
    # weld); imported lazily to avoid a module import cycle.
    from roofwall.cv.lines import measure_lines
    lines = measure_lines(labels, planes, transform, mask)
    debug = {
        "n_planes_kept": len(planes),
        "n_facets_traced": len(facets),
        "res_ft": round(transform.res, 3),
        "grid": [int(dsm.shape[0]), int(dsm.shape[1])],
        "roof_area_sqft": round(float(int((labels >= 0).sum()) * res2), 1),
        "facet_areas_sqft": sorted(
            (round(float(int((labels == i).sum()) * res2), 1) for i in range(len(planes))),
            reverse=True),
    }
    return snapped, lines, debug


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
    facets, lines, debug = recover_light(dsm_ft, mask, transform, priors)
    model = BuildingModel.from_edge_facets(
        to_roof_edges(facets), Origin(lat, lng), "solar-dsm")
    model.measured_lines = lines
    debug["n_solar_segments"] = len(segments)
    model.debug = debug
    return model

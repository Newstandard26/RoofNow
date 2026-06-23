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


def _merge_priors(priors, *, slope_tol: float = 0.03, z_tol: float = 1.0):
    """Collapse Solar over-segmentation. Google's Solar API often splits one
    physical roof plane into several roofSegmentStats; each becomes a near-equal
    plane prior (a, b, c). With several near-duplicates, assign_pixels splits a
    single facet's pixels between them on noise alone, fragmenting it. Merge
    priors whose plane coefficients match within tolerance so each physical
    plane is one prior. a, b are slopes (tan pitch); c is the plane's height (ft)
    extrapolated to the local origin, so z_tol distinguishes stacked roofs.

    Tolerances are deliberately tight: merging only true duplicates. On complex
    roofs Solar already *under*-segments (e.g. 11 segments for a 14-facet roof),
    so collapsing genuinely distinct neighbours into one averaged ("mongrel")
    plane is what spawns the shallow fits that misclassify hips as valleys.
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


def _seeded_component(region: np.ndarray, center_rc) -> np.ndarray:
    """8-connected flood fill of `region` (bool) from the pixel nearest center.

    The Solar mask covers every building in the 50 m tile, so a neighbouring
    house, garage or shed inflates the roof area and spawns phantom edges along
    the gap between structures. The tile is centred on the queried building, so
    keeping only the component containing the centre isolates the roof we mean.
    """
    from collections import deque

    if not region.any():
        return region
    nrows, ncols = region.shape
    cr, cc = center_rc
    if not (0 <= cr < nrows and 0 <= cc < ncols) or not region[cr, cc]:
        ys, xs = np.nonzero(region)
        k = int(np.argmin((ys - cr) ** 2 + (xs - cc) ** 2))
        cr, cc = int(ys[k]), int(xs[k])
    out = np.zeros_like(region)
    out[cr, cc] = True
    dq = deque([(cr, cc)])
    while dq:
        r, c = dq.popleft()
        for nr in (r - 1, r, r + 1):
            if not (0 <= nr < nrows):
                continue
            for nc in (c - 1, c, c + 1):
                if 0 <= nc < ncols and region[nr, nc] and not out[nr, nc]:
                    out[nr, nc] = True
                    dq.append((nr, nc))
    return out


# ---------- crease-watershed facet segmentation (pure numpy) ----------
# A roof facet is a smooth surface bounded by creases (ridge/hip/valley/eave,
# where the DSM bends). Tracing each plane's label set instead gives scattered,
# self-touching "star" facets on a complex roof. We segment by the creases: a
# marker-controlled watershed flooded from facet centres (points far from any
# crease), giving compact facets that tile the roof. Implemented in pure numpy
# (no scipy/skimage) to stay within the lightweight Vercel function.

def _gauss(a: np.ndarray, sigma: float) -> np.ndarray:
    """Separable Gaussian blur."""
    if sigma <= 0:
        return a
    rad = max(1, int(3 * sigma))
    xs = np.arange(-rad, rad + 1)
    k = np.exp(-(xs * xs) / (2 * sigma * sigma)); k /= k.sum()
    a = np.apply_along_axis(lambda m: np.convolve(m, k, mode="same"), 1, a)
    a = np.apply_along_axis(lambda m: np.convolve(m, k, mode="same"), 0, a)
    return a


def _fill_border(dsm: np.ndarray, mask: np.ndarray, iters: int = 6) -> np.ndarray:
    """Fill just-outside-mask pixels with the nearest in-mask height (a few
    passes) so DSM gradients at the roof border aren't corrupted by the hole."""
    f = dsm.copy(); known = mask.copy()
    h, w = f.shape
    for _ in range(iters):
        if known.all():
            break
        acc = np.zeros_like(f); cnt = np.zeros_like(f)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ys = slice(max(0, dy), h + min(0, dy)); ysrc = slice(max(0, -dy), h + min(0, -dy))
            xs = slice(max(0, dx), w + min(0, dx)); xsrc = slice(max(0, -dx), w + min(0, -dx))
            s = np.zeros_like(f); k2 = np.zeros_like(known)
            s[ys, xs] = np.where(known[ysrc, xsrc], f[ysrc, xsrc], 0.0)
            k2[ys, xs] = known[ysrc, xsrc]
            acc += s; cnt += k2
        new = (~known) & (cnt > 0)
        f[new] = acc[new] / cnt[new]; known |= new
    return f


def _maxfilter_diamond(a: np.ndarray, d: int) -> np.ndarray:
    """Grey dilation over a diamond of radius d (d 4-connected passes)."""
    m = a.copy()
    for _ in range(d):
        m2 = m.copy()
        m2[1:, :] = np.maximum(m2[1:, :], m[:-1, :]); m2[:-1, :] = np.maximum(m2[:-1, :], m[1:, :])
        m2[:, 1:] = np.maximum(m2[:, 1:], m[:, :-1]); m2[:, :-1] = np.maximum(m2[:, :-1], m[:, 1:])
        m = m2
    return m


def _peaks(flat: np.ndarray, mask: np.ndarray, min_d: int):
    """Local maxima of `flat` within `mask`, each at least min_d apart (greedy)."""
    mx = _maxfilter_diamond(np.where(mask, flat, -1e18), min_d)
    cand = mask & (flat >= mx - 1e-9)
    ys, xs = np.nonzero(cand)
    order = np.argsort(-flat[ys, xs])
    taken = np.zeros(mask.shape, dtype=bool); pts = []
    for idx in order.tolist():
        y, x = int(ys[idx]), int(xs[idx])
        if taken[max(0, y - min_d):y + min_d + 1, max(0, x - min_d):x + min_d + 1].any():
            continue
        pts.append((y, x)); taken[y, x] = True
    return pts


def _watershed(pri: np.ndarray, markers: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Marker-controlled watershed (Meyer flooding) on priority `pri`."""
    import heapq
    h, w = pri.shape
    out = markers.copy()
    inq = markers > 0
    heap = []; cnt = 0
    ys, xs = np.nonzero(markers > 0)
    for y, x in zip(ys.tolist(), xs.tolist()):
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and out[ny, nx] == 0 and not inq[ny, nx]:
                heapq.heappush(heap, (float(pri[ny, nx]), cnt, ny, nx)); cnt += 1; inq[ny, nx] = True
    while heap:
        _, _, y, x = heapq.heappop(heap)
        lbl = 0
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and out[ny, nx] > 0:
                lbl = out[ny, nx]; break
        out[y, x] = lbl
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and out[ny, nx] == 0 and not inq[ny, nx]:
                heapq.heappush(heap, (float(pri[ny, nx]), cnt, ny, nx)); cnt += 1; inq[ny, nx] = True
    return out


def _crease_watershed_facets(dsm, region, transform, planes, Xg, Yg,
                             simplify_ft, min_area_sqft, *, min_sep_ft=6.5,
                             slope_tol=0.08, z_tol=2.0):
    """Segment `region` (one building footprint) into compact facet polygons by
    its DSM creases. Returns [{"id", "verts"}] ready for snapping/diagram."""
    ys, xs = np.nonzero(region)
    if len(ys) == 0:
        return []
    r0, r1 = int(ys.min()), int(ys.max()) + 1
    c0, c1 = int(xs.min()), int(xs.max()) + 1
    m = region[r0:r1, c0:c1]
    d = dsm[r0:r1, c0:c1].astype(float)
    ds = _gauss(_fill_border(d, m), 1.0)
    gy, gx = np.gradient(ds)
    crease = _gauss(np.abs(np.gradient(gx, axis=1)) + np.abs(np.gradient(gx, axis=0))
                    + np.abs(np.gradient(gy, axis=1)) + np.abs(np.gradient(gy, axis=0)), 0.6)
    cmax = float(crease.max()) if crease.size else 1.0
    crease = np.where(m, crease, cmax)
    flat = np.where(m, cmax - crease, -1e18)
    min_d = max(4, int(round(min_sep_ft / max(transform.res, 1e-6))))
    pts = _peaks(flat, m, min_d)
    if not pts:
        return []
    markers = np.zeros(m.shape, dtype=int)
    for k, (y, x) in enumerate(pts, 1):
        markers[y, x] = k
    seg = _watershed(crease, markers, m)
    nreg = int(seg.max())
    if nreg == 0:
        return []

    cmw, cmh = c0, r0

    # Fit a plane to each watershed region. Two regions are really one facet when
    # their fitted planes match (a weak crease split one surface); distinct facets
    # (real ridge/hip/valley between them) have different planes.
    fit_of: dict = {}
    for k in range(1, nreg + 1):
        rr, cc = np.nonzero(seg == k)
        if len(rr) == 0:
            continue
        wx = Xg[cmh + rr, cmw + cc]; wy = Yg[cmh + rr, cmw + cc]; wz = d[rr, cc]
        fit_of[k] = _fit_plane(wx, wy, wz) or (0.0, 0.0, float(np.mean(wz)))

    def _similar(p, q):
        return (abs(p[0] - q[0]) <= slope_tol and abs(p[1] - q[1]) <= slope_tol
                and abs(p[2] - q[2]) <= z_tol)

    h2, w2 = seg.shape
    parent = {k: k for k in range(1, nreg + 1)}
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    for rr in range(h2):
        for cc in range(w2):
            a = seg[rr, cc]
            if a <= 0:
                continue
            for dy, dx in ((1, 0), (0, 1)):
                ny, nx = rr + dy, cc + dx
                if ny < h2 and nx < w2:
                    b = seg[ny, nx]
                    if b > 0 and b != a and find(a) != find(b) \
                            and _similar(fit_of[a], fit_of[b]):
                        parent[find(a)] = find(b)

    groups: dict = {}
    for k in range(1, nreg + 1):
        groups.setdefault(find(k), []).append(k)

    def plane_for(rm):
        rr, cc = np.nonzero(rm)
        wx = Xg[cmh + rr, cmw + cc]; wy = Yg[cmh + rr, cmw + cc]; wz = d[rr, cc]
        return min(range(len(planes)), key=lambda i: float(np.mean(np.abs(
            planes[i][0] * wx + planes[i][1] * wy + planes[i][2] - wz))))

    res2 = transform.res * transform.res
    min_px = max(8, int(min_area_sqft / res2))
    full = np.zeros(dsm.shape, dtype=bool)
    facets = []
    for root, ks in groups.items():
        small = np.isin(seg, ks)
        if int(small.sum()) < min_px:
            continue
        idx = plane_for(small)
        full[:] = False; full[r0:r1, c0:c1] = small
        verts = _trace_region(full, planes[idx], transform, simplify_ft)
        if len(verts) >= 3 and _poly_area_sqft(verts) >= min_area_sqft:
            facets.append({"id": f"{idx}.{root}", "verts": verts})
    return facets


def _erode4(r: np.ndarray) -> np.ndarray:
    """4-connected binary erosion (out-of-bounds treated as background)."""
    up = np.zeros_like(r); up[1:, :] = r[:-1, :]
    dn = np.zeros_like(r); dn[:-1, :] = r[1:, :]
    lf = np.zeros_like(r); lf[:, 1:] = r[:, :-1]
    rt = np.zeros_like(r); rt[:, :-1] = r[:, 1:]
    return r & up & dn & lf & rt


def _dilate4(r: np.ndarray) -> np.ndarray:
    """4-connected binary dilation."""
    out = r.copy()
    out[1:, :] |= r[:-1, :]
    out[:-1, :] |= r[1:, :]
    out[:, 1:] |= r[:, :-1]
    out[:, :-1] |= r[:, 1:]
    return out


def _open(r: np.ndarray, iters: int = 1) -> np.ndarray:
    """Binary opening: erode then dilate. Removes thin (<= iters px) necks and
    spurs that pinch a facet's traced contour into a self-touching star, while
    keeping the bulk shape/area. Diagram cleanup only (line lengths are measured
    from the label map + planes, not these polygons)."""
    e = r
    for _ in range(iters):
        e = _erode4(e)
    for _ in range(iters):
        e = _dilate4(e)
    return e


def _connected_components(region: np.ndarray):
    """Yield a boolean mask for each 8-connected component of `region` (bool).

    One fitted plane is keyed by orientation (pitch/azimuth/height), so two
    physically-separate facets that face the same way land on the same label.
    Tracing that label as one region gives a scattered, self-overlapping "star"
    polygon. Splitting it into connected components turns each into its own
    compact facet for the diagram (line lengths read the label map directly and
    are unaffected).
    """
    from collections import deque

    region = np.asarray(region, dtype=bool)
    seen = np.zeros_like(region)
    nrows, ncols = region.shape
    ys, xs = np.nonzero(region)
    for y0, x0 in zip(ys.tolist(), xs.tolist()):
        if seen[y0, x0]:
            continue
        comp = np.zeros_like(region)
        comp[y0, x0] = True
        seen[y0, x0] = True
        dq = deque([(y0, x0)])
        while dq:
            r, c = dq.popleft()
            for nr in (r - 1, r, r + 1):
                if not (0 <= nr < nrows):
                    continue
                for nc in (c - 1, c, c + 1):
                    if 0 <= nc < ncols and region[nr, nc] and not seen[nr, nc]:
                        seen[nr, nc] = True
                        comp[nr, nc] = True
                        dq.append((nr, nc))
        yield comp


def _smooth_labels(labels, nplanes, iters=2):
    """Majority filter the label map so each facet is a solid contiguous blob.

    Similar planes otherwise interleave pixel-by-pixel (salt-and-pepper), which
    spawns fake facet adjacencies and inflates the projected length of every
    shared edge. Each pixel adopts the label most common among itself + its 4
    neighbours; assigned pixels never become holes.
    """
    L = labels
    valid = L >= 0
    for _ in range(max(0, iters)):
        best_c = np.zeros(L.shape, dtype=np.int16)
        best_l = np.full(L.shape, -1, dtype=L.dtype)
        for i in range(nplanes):
            m = (L == i).astype(np.int16)
            c = m.copy()                       # include self
            c[1:, :] += m[:-1, :]; c[:-1, :] += m[1:, :]
            c[:, 1:] += m[:, :-1]; c[:, :-1] += m[:, 1:]
            upd = c > best_c
            best_c = np.where(upd, c, best_c)
            best_l = np.where(upd, i, best_l)
        L = np.where(valid, best_l, -1)
    return L


def _largest_component(region: np.ndarray) -> np.ndarray:
    """Boolean mask of the largest 8-connected component of `region`."""
    best = None
    best_n = 0
    for comp in _connected_components(region):
        n = int(comp.sum())
        if n > best_n:
            best_n, best = n, comp
    return best if best is not None else np.zeros_like(region, dtype=bool)


def _fill_holes(region: np.ndarray) -> np.ndarray:
    """Fill interior holes of `region` (background pixels unreachable from the
    array border) so a facet trace doesn't carve a donut around a vent/AC unit."""
    from collections import deque

    h, w = region.shape
    bg = np.zeros_like(region, dtype=bool)
    dq = deque()
    for r in range(h):
        for c in (0, w - 1):
            if not region[r, c] and not bg[r, c]:
                bg[r, c] = True
                dq.append((r, c))
    for c in range(w):
        for r in (0, h - 1):
            if not region[r, c] and not bg[r, c]:
                bg[r, c] = True
                dq.append((r, c))
    while dq:
        r, c = dq.popleft()
        for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
            if 0 <= nr < h and 0 <= nc < w and not region[nr, nc] and not bg[nr, nc]:
                bg[nr, nc] = True
                dq.append((nr, nc))
    return region | ~bg


def _flood_fill_orphans(clean: np.ndarray, component: np.ndarray) -> None:
    """In place: assign every still-unlabelled footprint pixel to its nearest
    labelled facet (multi-source 4-connected BFS) so the facets tile the roof."""
    from collections import deque

    h, w = clean.shape
    dq = deque(zip(*np.nonzero(clean >= 0)))
    while dq:
        r, c = dq.popleft()
        lab = clean[r, c]
        for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
            if 0 <= nr < h and 0 <= nc < w and component[nr, nc] and clean[nr, nc] < 0:
                clean[nr, nc] = lab
                dq.append((nr, nc))


def _coherent_facets(dlabels, dplanes, component, dsm, Xg, Yg, transform, *,
                     simplify_ft, min_facet_area_px, min_facet_area_sqft,
                     open_iters=2, grow_iters=2):
    """Turn the (coherent) PEARL label map into clean, compact facet polygons.

    The PEARL partition is spatially smooth but a facet's label can still send a
    thin tendril into a busy ridge junction, which pinches an independent trace
    into a self-touching "star". Per label we keep its largest component, OPEN it
    (erode/dilate by ``open_iters``) to sever those tendrils, then build one
    gap-free, footprint-tiling label map: pixels orphaned by the opening are
    re-assigned to the nearest facet, and any leftover sub-threshold strips are
    dissolved into their neighbours. Each facet is then traced and grown a couple
    of pixels (``grow_iters``) so neighbours overlap by a hair instead of leaving
    hairline gaps at the staircase boundary — snap_model welds the shared verts.
    """
    h, w = dlabels.shape
    res2 = transform.res * transform.res
    clean = np.full((h, w), -1, dtype=int)
    best = np.full((h, w), np.inf, dtype=float)
    for i in range(len(dplanes)):
        m = _largest_component(dlabels == i)
        if int(m.sum()) < min_facet_area_px:
            continue
        for _ in range(open_iters):
            m = _erode4(m)
        m = _largest_component(m)
        for _ in range(open_iters):
            m = _dilate4(m)
        m &= component
        if int(m.sum()) < min_facet_area_px:
            continue
        a, b, c = dplanes[i]
        resid = np.abs(a * Xg + b * Yg + c - dsm)
        take = m & (resid < best)
        clean[take] = i
        best[take] = resid[take]
    _flood_fill_orphans(clean, component)

    # Dissolve thin sub-threshold strips into their neighbours so no tiny region
    # drops out of tracing and leaves a wedge gap at a junction.
    min_px = max(1, int(min_facet_area_sqft / res2))
    for _ in range(4):
        kill = np.zeros((h, w), dtype=bool)
        for i in range(len(dplanes)):
            for comp in _connected_components(clean == i):
                if int(comp.sum()) < min_px:
                    kill |= comp
        if not kill.any():
            break
        clean[kill] = -1
        _flood_fill_orphans(clean, component)

    facets = []
    for i in range(len(dplanes)):
        for ci, comp in enumerate(_connected_components(clean == i)):
            if int(comp.sum()) * res2 < min_facet_area_sqft:
                continue
            comp = _fill_holes(comp)
            for _ in range(grow_iters):
                comp = _dilate4(comp)
            comp &= component
            verts = _trace_region(comp, dplanes[i], transform, simplify_ft)
            if len(verts) >= 3 and _poly_area_sqft(verts) >= min_facet_area_sqft:
                facets.append({"id": f"{i}.{ci}" if ci else str(i), "verts": verts})
    return facets


def _pearl_labels(dsm, region, transform, Xg, Yg, planes, *,
                  lam=1.0, iters=4, rmax=6.0):
    """Coherent plane labelling by graph-cut energy minimization (PEARL).

    Greedy nearest-plane labelling has no spatial term, so on a complex roof one
    plane wins scattered pixels and facets come out as jagged "stars". Here each
    footprint pixel is labelled by alpha-expansion minimizing
        sum_p |plane(l_p) - dsm_p|  +  lam * sum_{p~q} [l_p != l_q]
    i.e. a data term (height residual to the plane) plus a Potts spatial-
    smoothness term that forces compact, contiguous facets with clean borders.
    Planes are refit to their pixels between passes (the EM step of PEARL).
    Returns (full-grid labels, refined planes). Falls back to greedy if
    PyMaxflow is unavailable.
    """
    full = np.full(dsm.shape, -1, dtype=int)
    ys, xs = np.nonzero(region)
    if len(ys) == 0:
        return full, planes
    try:
        import maxflow.fastmin as _fm
    except Exception:  # noqa: BLE001 - degrade gracefully if the dep is missing
        labels = assign_pixels(dsm, region.astype("uint8"), planes, transform, 1e9)
        return labels, planes

    r0, r1 = int(ys.min()), int(ys.max()) + 1
    c0, c1 = int(xs.min()), int(xs.max()) + 1
    m = region[r0:r1, c0:c1]
    X = Xg[r0:r1, c0:c1]; Y = Yg[r0:r1, c0:c1]; Z = dsm[r0:r1, c0:c1]
    P = [list(p) for p in planes]
    L = len(P)
    V = (lam * (1.0 - np.eye(L)))
    lab = None
    for _ in range(max(1, iters)):
        Dc = np.empty((m.shape[0], m.shape[1], L), dtype=np.float64)
        for l, (a, b, c) in enumerate(P):
            Dc[:, :, l] = np.minimum(np.abs(a * X + b * Y + c - Z), rmax)
        Dc[~m, :] = 0.0                       # outside footprint: neutral
        lab = _fm.aexpansion_grid(np.ascontiguousarray(Dc), V).astype(int)
        lab = np.where(m, lab, -1)
        refit = []
        for l in range(L):
            sel = lab == l
            refit.append(list(_fit_plane(X[sel], Y[sel], Z[sel]) or P[l])
                         if int(sel.sum()) >= 20 else P[l])
        if refit == P:
            break
        P = refit
    full[r0:r1, c0:c1] = lab
    return full, [tuple(p) for p in P]


def recover_light(dsm, mask, transform, priors, *, max_residual=2.0, simplify_ft=1.8,
                  snap_tol=2.5, edge_tol=1.5, min_facet_area_px=24,
                  min_facet_area_sqft=25.0, min_keep_sqft=40.0, refine_iters=4,
                  smooth_iters=4, pearl_lambda=1.8):
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

    # Isolate the queried building (drop neighbouring structures in the 50 m
    # tile so they don't inflate area or spawn phantom edges).
    filled = assign_pixels(dsm, mask, planes, transform, max_residual=1e9)
    mask_sqft = float(int((filled >= 0).sum()) * res2)
    component = _seeded_component(filled >= 0, (nrows // 2, ncols // 2))

    # MEASUREMENT labels (line lengths): nearest-plane fill + majority smooth.
    # These are measured edge-by-edge against the plane intersections; the raw
    # (slightly jagged) borders capture true ridge/hip/valley length well, so
    # this is kept as the validated source for line_lengths below.
    labels = np.where(component, filled, -1)
    labels = _smooth_labels(labels, len(planes), smooth_iters)

    # DIAGRAM labels: PEARL graph-cut labelling adds a spatial-smoothness term,
    # yielding a clean, coherent partition (compact facets, no scattered "star")
    # for the roof plan. Decoupled from measurement so the validated line lengths
    # don't change. _coherent_facets turns that partition into clean, gap-free,
    # footprint-tiling facet polygons (sever tendrils, dissolve strips, weld).
    dlabels, dplanes = _pearl_labels(dsm, component, transform, Xg, Yg, planes,
                                     lam=pearl_lambda, iters=4)
    dlabels = _smooth_labels(dlabels, len(dplanes), 1)
    dlabels = np.where(component, dlabels, -1)
    facets = _coherent_facets(dlabels, dplanes, component, dsm, Xg, Yg, transform,
                              simplify_ft=simplify_ft,
                              min_facet_area_px=min_facet_area_px,
                              min_facet_area_sqft=min_facet_area_sqft)
    snapped = snap_model(facets, snap_tol=snap_tol, edge_tol=edge_tol)
    # Line lengths from the plane geometry (accurate even when facets don't
    # weld); imported lazily to avoid a module import cycle.
    from roofwall.cv.lines import measure_lines
    seg_diag: list = []
    lines = measure_lines(labels, planes, transform, mask, dsm=dsm, diag=seg_diag)
    debug = {
        "n_planes_kept": len(planes),
        "n_facets_traced": len(facets),
        "res_ft": round(transform.res, 3),
        "grid": [int(dsm.shape[0]), int(dsm.shape[1])],
        "roof_area_sqft": round(float(int((labels >= 0).sum()) * res2), 1),
        "mask_sqft": round(mask_sqft, 1),
        "facet_areas_sqft": sorted(
            (round(float(int((labels == i).sum()) * res2), 1) for i in range(len(planes))),
            reverse=True),
        "planes_abc": [[round(p[0], 3), round(p[1], 3), round(p[2], 1)] for p in planes],
        "segs": seg_diag,
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

    # Anchor the DSM/mask fetch to the building's centre, not the raw click.
    # Google returns a Data-Layer tile centred on the query point, so two clicks
    # ~8 ft apart on the SAME roof pull different tiles/masks and produce very
    # different line lengths. building_insights returns the same building (and
    # centre) for any click on it, so centring there makes the measurement
    # stable: the same roof always yields the same numbers.
    center = payload.get("center") or {}
    blat = float(center.get("latitude", lat))
    blng = float(center.get("longitude", lng))

    layers = client.data_layers(blat, blng, 50.0)
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
    debug["anchor"] = {"query": [round(lat, 7), round(lng, 7)],
                       "building_center": [round(blat, 7), round(blng, 7)]}
    model.debug = debug
    return model

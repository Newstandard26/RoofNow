"""
recover.py — Solar DSM raster -> facet polygons (the step that creates the shapes).

This is the missing engine: it turns a Digital Surface Model (height raster) plus the
Solar roof-segment planes into clean 3D facet polygons, which then flow through
snapping (shared-edge fix) and edges (line lengths) and finally a diagram.

Pipeline (approach A of the boundary-recovery spec):
  1. plane priors from Solar roofSegmentStats  -> plane equations z = a*x + b*y + c
  2. assign each building pixel to its best-fit plane (min height residual)
  3. trace + simplify each plane's region into a polygon (skimage + shapely)
  4. lift polygon vertices to 3D via the plane
  5. snap_model() so adjacent facets share exact edges
  -> hand to edges for ridge/hip/valley/eave/rake lengths.

Deps: numpy, scikit-image, shapely. The synthetic round-trip in test_recover.py
validates the whole chain without any live API call.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np
from skimage import measure
from shapely.geometry import Polygon

from roofwall.measurement.snapping import snap_model

Vec = Tuple[float, float, float]
ABC = Tuple[float, float, float]  # plane z = a*x + b*y + c


@dataclass
class RasterTransform:
    """Maps raster (row, col) <-> local world (x=East, y=North) in feet.
    Row 0 is the TOP of the array (max Y)."""
    x0: float           # world X at col 0
    y0: float           # world Y at the BOTTOM row
    res: float          # feet per pixel
    nrows: int

    def colrow_to_world(self, col: float, row: float) -> Tuple[float, float]:
        return (self.x0 + col * self.res, self.y0 + (self.nrows - 1 - row) * self.res)

    def grids(self, ncols: int) -> Tuple[np.ndarray, np.ndarray]:
        cols = np.arange(ncols)
        rows = np.arange(self.nrows)
        X = self.x0 + cols[None, :] * self.res
        Y = self.y0 + (self.nrows - 1 - rows[:, None]) * self.res
        Xg = np.broadcast_to(X, (self.nrows, ncols))
        Yg = np.broadcast_to(Y, (self.nrows, ncols))
        return Xg, Yg


# ---------- plane helpers ----------
def abc_from_normal(normal: Vec, point: Vec) -> ABC:
    nx, ny, nz = normal
    if abs(nz) < 1e-9:
        nz = 1e-9
    a = -nx / nz
    b = -ny / nz
    c = point[2] - a * point[0] - b * point[1]
    return (a, b, c)


def plane_from_solar_segment(pitch_deg: float, azimuth_deg: float, point: Vec) -> ABC:
    """Build a plane from a Solar roofSegmentStat.
    azimuth = compass direction of downslope (0=N, 90=E, 180=S, 270=W).
    x = East, y = North."""
    slope = math.tan(math.radians(pitch_deg))  # rise/run
    az = math.radians(azimuth_deg)
    # downslope horizontal unit vector (East, North)
    de, dn = math.sin(az), math.cos(az)
    # z decreases by `slope` per unit travelled downslope => gradient = -slope*(de,dn)
    a = -slope * de
    b = -slope * dn
    c = point[2] - a * point[0] - b * point[1]
    return (a, b, c)


def plane_z(p: ABC, x: float, y: float) -> float:
    return p[0] * x + p[1] * y + p[2]


# ---------- step 2: assign pixels to planes ----------
def assign_pixels(dsm: np.ndarray, mask: np.ndarray, planes: List[ABC],
                  transform: RasterTransform, max_residual: float = 2.0) -> np.ndarray:
    """Return an int label array: index of best-fit plane per pixel, -1 where unassigned."""
    nrows, ncols = dsm.shape
    Xg, Yg = transform.grids(ncols)
    resid = np.full((len(planes), nrows, ncols), np.inf, dtype=float)
    for i, (a, b, c) in enumerate(planes):
        pred = a * Xg + b * Yg + c
        resid[i] = np.abs(pred - dsm)
    labels = np.argmin(resid, axis=0)
    best = np.min(resid, axis=0)
    labels = np.where(mask > 0, labels, -1)
    labels = np.where(best <= max_residual, labels, -1)
    return labels.astype(int)


# ---------- step 3+4: trace a region into a 3D polygon ----------
def trace_facet_polygon(region: np.ndarray, plane: ABC, transform: RasterTransform,
                        simplify_ft: float = 0.7) -> List[Vec]:
    """region: binary mask of one facet. Returns simplified 3D polygon (>=3 verts) or []."""
    padded = np.pad(region.astype(float), 1, mode="constant", constant_values=0)
    contours = measure.find_contours(padded, 0.5)
    if not contours:
        return []
    contour = max(contours, key=len)  # outer boundary
    pts2d = []
    for r, col in contour:
        x, y = transform.colrow_to_world(col - 1, r - 1)  # undo pad
        pts2d.append((x, y))
    if len(pts2d) < 4:
        return []
    poly = Polygon(pts2d)
    if not poly.is_valid or poly.area <= 0:
        poly = Polygon(pts2d).buffer(0)
        if poly.is_empty:
            return []
        if poly.geom_type == "MultiPolygon":
            poly = max(poly.geoms, key=lambda g: g.area)
    poly = poly.simplify(simplify_ft, preserve_topology=True)
    coords = list(poly.exterior.coords)[:-1]  # drop closing dup
    if len(coords) < 3:
        return []
    return [(x, y, plane_z(plane, x, y)) for (x, y) in coords]


# ---------- full recovery ----------
def recover(dsm: np.ndarray, mask: np.ndarray, transform: RasterTransform,
            priors: List[Dict], max_residual: float = 2.0, simplify_ft: float = 1.0,
            snap_tol: float = 1.2, edge_tol: float = 0.9,
            min_facet_area_px: int = 12) -> List[Dict]:
    """
    priors: list of {"id": str, "abc": (a,b,c)}  (use plane_from_solar_segment to build abc).
    Returns snapped plain facets [{"id", "verts": [(x,y,z)...]}] ready for edges.
    """
    planes = [p["abc"] for p in priors]
    labels = assign_pixels(dsm, mask, planes, transform, max_residual)

    facets: List[Dict] = []
    for i, prior in enumerate(priors):
        region = labels == i
        if int(region.sum()) < min_facet_area_px:
            continue
        verts = trace_facet_polygon(region, planes[i], transform, simplify_ft)
        if len(verts) >= 3:
            facets.append({"id": prior["id"], "verts": verts})

    return snap_model(facets, snap_tol=snap_tol, edge_tol=edge_tol)

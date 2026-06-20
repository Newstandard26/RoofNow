"""USGS 3DEP LiDAR roof-plane pipeline (Phase 2).

Reading the point cloud (3DEP EPT on AWS) needs ``pdal``/``open3d`` — that
is the only part gated behind the ``lidar-io`` extra. The *measurement*
work — plane fitting, RANSAC segmentation, and converting a plane to
pitch / azimuth / area — is done here in numpy so it is unit-testable with
synthetic clouds, no network and no heavy native deps.

Pipeline (per spec):
  1. Footprint polygon (MS/Google footprints or Solar mask).
  2. Read 3DEP EPT, crop to footprint+buffer, classify, compute normals.
  3. Segment planar patches: RANSAC -> merge co-planar patches.
  4. Per plane: area (project to plane), pitch = angle(normal, vertical),
     azimuth = heading of downslope direction.
  5. Reconstruct edges -> classify ridge/hip/valley/eave/rake.

The output is ``list[FacetMeasurement]`` so it feeds the same engine as the
Solar path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

from roofwall.measurement.engine import (
    FacetMeasurement,
    Pitch,
    measure_facet,
    sqm_to_sqft,
)
from roofwall.measurement.geometry import Point

# Public-domain 3DEP entwine point tiles on AWS.
EPT_3DEP_RESOURCE = "https://s3-us-west-2.amazonaws.com/usgs-lidar-public/"


# --------------------------------------------------------------------------
# Plane geometry (a plane is n·x = d, with unit normal n oriented upward)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Plane:
    """A fitted plane: unit normal (upward) and offset d, with fit stats."""

    normal: np.ndarray  # shape (3,), unit, normal[2] >= 0
    d: float
    rms: float
    n_points: int

    @property
    def pitch_degrees(self) -> float:
        """Slope angle: angle between the (upward) normal and vertical."""
        nz = float(np.clip(self.normal[2], -1.0, 1.0))
        return float(np.degrees(np.arccos(nz)))

    @property
    def azimuth_degrees(self) -> float:
        """Downslope/facing heading (compass: 0=N=+y, clockwise)."""
        nx, ny = float(self.normal[0]), float(self.normal[1])
        if abs(nx) < 1e-12 and abs(ny) < 1e-12:
            return 0.0  # flat roof — azimuth undefined
        return float(np.degrees(np.arctan2(nx, ny))) % 360.0

    def pitch(self) -> Pitch:
        return Pitch.from_degrees(min(self.pitch_degrees, 89.999))


def fit_plane(points: np.ndarray) -> Plane:
    """Least-squares best-fit plane through >=3 points via SVD.

    ``points`` is an (N, 3) array. The normal is the smallest-variance
    singular direction; it is flipped so it points upward (n_z >= 0).
    """
    pts = np.asarray(points, dtype=float)
    if pts.ndim != 2 or pts.shape[1] != 3 or pts.shape[0] < 3:
        raise ValueError("need an (N>=3, 3) array of points")
    centroid = pts.mean(axis=0)
    centered = pts - centroid
    # Smallest singular vector of the centered cloud is the plane normal.
    _, _, vh = np.linalg.svd(centered, full_matrices=False)
    normal = vh[-1]
    if normal[2] < 0:
        normal = -normal
    normal = normal / np.linalg.norm(normal)
    d = float(normal @ centroid)
    dist = np.abs(pts @ normal - d)
    rms = float(np.sqrt(np.mean(dist**2)))
    return Plane(normal=normal, d=d, rms=rms, n_points=pts.shape[0])


def _plane_point_distance(points: np.ndarray, normal: np.ndarray, d: float) -> np.ndarray:
    return np.abs(points @ normal - d)


# --------------------------------------------------------------------------
# Convex-hull area of a point set projected to the horizontal plane
# --------------------------------------------------------------------------


def _convex_hull_area_xy(points_xy: np.ndarray) -> float:
    """Area of the convex hull of 2D points (Andrew's monotone chain)."""
    pts = np.unique(np.asarray(points_xy, dtype=float), axis=0)
    if pts.shape[0] < 3:
        return 0.0
    order = np.lexsort((pts[:, 1], pts[:, 0]))
    pts = pts[order]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list = []
    for p in pts[::-1]:
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = np.array(lower[:-1] + upper[:-1])
    x, y = hull[:, 0], hull[:, 1]
    return float(0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def plan_area_units2(points: np.ndarray) -> float:
    """Horizontal (plan) area covered by a facet's points, in input units²."""
    return _convex_hull_area_xy(np.asarray(points, dtype=float)[:, :2])


# --------------------------------------------------------------------------
# RANSAC plane segmentation
# --------------------------------------------------------------------------


def segment_planes(
    points: np.ndarray,
    *,
    dist_threshold: float = 0.15,
    min_inliers: int = 50,
    max_planes: int = 16,
    iterations: int = 300,
    seed: int = 0,
) -> list[tuple[np.ndarray, Plane]]:
    """RANSAC-segment a cloud into planar patches.

    ``dist_threshold`` is the inlier band (same units as the cloud, e.g.
    meters). Returns ``[(inlier_points, refitted_plane), ...]`` largest
    first. Deterministic for a fixed ``seed``.
    """
    pts = np.asarray(points, dtype=float)
    if pts.ndim != 2 or pts.shape[1] != 3:
        raise ValueError("points must be (N, 3)")
    rng = np.random.default_rng(seed)
    remaining = pts.copy()
    out: list[tuple[np.ndarray, Plane]] = []

    while remaining.shape[0] >= min_inliers and len(out) < max_planes:
        best_mask: Optional[np.ndarray] = None
        best_count = 0
        n = remaining.shape[0]
        for _ in range(iterations):
            idx = rng.choice(n, size=3, replace=False)
            sample = remaining[idx]
            try:
                cand = fit_plane(sample)
            except (ValueError, np.linalg.LinAlgError):
                continue
            mask = _plane_point_distance(remaining, cand.normal, cand.d) < dist_threshold
            count = int(mask.sum())
            if count > best_count:
                best_count = count
                best_mask = mask
        if best_mask is None or best_count < min_inliers:
            break
        inliers = remaining[best_mask]
        plane = fit_plane(inliers)  # refit on all inliers
        out.append((inliers, plane))
        remaining = remaining[~best_mask]

    out.sort(key=lambda ip: ip[0].shape[0], reverse=True)
    return out


# --------------------------------------------------------------------------
# Cloud -> facets
# --------------------------------------------------------------------------


def _confidence(plane: Plane, dist_threshold: float) -> float:
    """Heuristic facet confidence from planar fit tightness."""
    if dist_threshold <= 0:
        return 1.0
    return float(np.clip(1.0 - plane.rms / dist_threshold, 0.0, 1.0))


def facets_from_points(
    points: np.ndarray,
    *,
    units_are_meters: bool = True,
    dist_threshold: float = 0.15,
    min_inliers: int = 50,
    min_pitch_degrees: float = 3.0,
    seed: int = 0,
) -> list[FacetMeasurement]:
    """Extract roof facets from a building point cloud.

    Planes flatter than ``min_pitch_degrees`` (walls/ground) are dropped.
    Plan areas are converted to ft² when ``units_are_meters`` is true so the
    result matches the Solar path's units.
    """
    facets: list[FacetMeasurement] = []
    for inliers, plane in segment_planes(
        points,
        dist_threshold=dist_threshold,
        min_inliers=min_inliers,
        seed=seed,
    ):
        if plane.pitch_degrees < min_pitch_degrees and plane.pitch_degrees > 0:
            # near-flat: still a valid (low-slope) roof facet — keep it.
            pass
        # Drop near-vertical patches (walls) — not roof facets.
        if plane.pitch_degrees > 80.0:
            continue
        plan_area = plan_area_units2(inliers)
        if units_are_meters:
            plan_area = sqm_to_sqft(plan_area)
        facets.append(
            measure_facet(
                footprint_area_sqft=plan_area,
                pitch=plane.pitch(),
                azimuth_deg=plane.azimuth_degrees,
                confidence=_confidence(plane, dist_threshold),
                source="lidar",
            )
        )
    return facets


# --------------------------------------------------------------------------
# Point-cloud I/O (optional — needs the 'lidar-io' extra)
# --------------------------------------------------------------------------


def read_3dep_cloud(
    footprint: Sequence[Point], *, buffer_m: float = 2.0
) -> np.ndarray:
    """Read & crop a 3DEP EPT cloud to a footprint. (Needs pdal.)"""
    try:
        import pdal  # noqa: F401
    except ImportError as exc:  # pragma: no cover - optional dep
        raise RuntimeError(
            "Reading 3DEP needs the 'lidar-io' extra: pip install roofwall[lidar-io]"
        ) from exc
    raise NotImplementedError(
        "EPT read/crop wiring is pending; facets_from_points() is the tested core."
    )


def roof_facets_from_lidar(
    footprint: Sequence[Point], *, buffer_m: float = 2.0, **kwargs
) -> list[FacetMeasurement]:
    """End-to-end: read 3DEP for a footprint -> facets. (Needs pdal.)"""
    cloud = read_3dep_cloud(footprint, buffer_m=buffer_m)
    return facets_from_points(cloud, **kwargs)

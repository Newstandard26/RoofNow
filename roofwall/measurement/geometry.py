"""Planar geometry helpers for footprints & facet outlines.

Pure stdlib (no numpy/shapely) so the engine has zero install footprint.
Coordinates are 2-tuples ``(x, y)`` in a projected, equal-distance CRS
(e.g. UTM feet/meters) — NOT raw lat/lng. Project before using these.
"""

from __future__ import annotations

import math
from typing import Sequence

Point = tuple[float, float]
Polygon = Sequence[Point]


def polygon_area(points: Polygon) -> float:
    """Absolute area of a simple polygon via the shoelace formula.

    Orientation-independent (returns the absolute value). The ring may be
    open or closed (first point repeated); both are handled.
    """
    pts = _as_open_ring(points)
    n = len(pts)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def polygon_perimeter(points: Polygon) -> float:
    """Perimeter length of a polygon ring."""
    pts = _as_open_ring(points)
    n = len(pts)
    if n < 2:
        return 0.0
    total = 0.0
    for i in range(n):
        total += distance(pts[i], pts[(i + 1) % n])
    return total


def distance(a: Point, b: Point) -> float:
    """Euclidean distance between two points."""
    return math.hypot(b[0] - a[0], b[1] - a[1])


def bearing_degrees(a: Point, b: Point) -> float:
    """Compass-style bearing a->b in degrees (0=+y/North, clockwise)."""
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    return math.degrees(math.atan2(dx, dy)) % 360.0


def signed_area(points: Polygon) -> float:
    """Signed shoelace area; positive = counter-clockwise winding."""
    pts = _as_open_ring(points)
    n = len(pts)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def centroid(points: Polygon) -> Point:
    """Area centroid of a simple polygon."""
    pts = _as_open_ring(points)
    n = len(pts)
    if n < 3:
        # Degenerate: fall back to vertex mean.
        cx = sum(p[0] for p in pts) / max(n, 1)
        cy = sum(p[1] for p in pts) / max(n, 1)
        return (cx, cy)
    a = signed_area(pts)
    if a == 0:
        cx = sum(p[0] for p in pts) / n
        cy = sum(p[1] for p in pts) / n
        return (cx, cy)
    cx = cy = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        cross = x1 * y2 - x2 * y1
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    cx /= 6.0 * a
    cy /= 6.0 * a
    return (cx, cy)


def _as_open_ring(points: Polygon) -> list[Point]:
    """Return vertices with any duplicated closing point removed."""
    pts = list(points)
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts = pts[:-1]
    return pts

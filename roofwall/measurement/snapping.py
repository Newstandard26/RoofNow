"""
snapping.py — make independently-traced roof facet polygons share exact edges.

This is the step that makes boundary recovery actually work. When you trace each
facet's outline separately (from a DSM raster or LiDAR), adjacent facets do NOT end
up with identical shared vertices — they're off by a few inches. ``edges`` then
sees every shared edge as two separate boundary edges, so ridges/hips/valleys
disappear and eaves/rakes explode. This module fixes that, in three passes:

  1. snap_vertices()      — merge near-coincident vertices across all facets.
  2. resolve_t_junctions()— where one facet's vertex lies ON another facet's edge,
                            insert it so the two facets share that point (T-junctions).
  3. drop_collinear()     — remove redundant straight-line vertices, but PRESERVE any
                            vertex shared by >1 facet (those are real corners / the
                            T-junction points we just inserted).

Pure stdlib. Operates on plain dicts: {"id": str, "verts": [(x,y,z), ...]} (feet).
Use to_roof_edges() to hand the result to :mod:`roofwall.measurement.edges` for line
lengths; :func:`weld` is a convenience wrapper that does the round-trip on EdgeFacets.
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple

Vec = Tuple[float, float, float]
PlainFacet = Dict[str, object]  # {"id": str, "verts": List[Vec]}

DEFAULT_SNAP = 0.25  # ft, merge vertices closer than this
DEFAULT_ON_EDGE = 0.10  # ft, treat a point as "on" an edge within this perpendicular dist


# ---------- vector helpers ----------
def _sub(a: Vec, b: Vec) -> Vec: return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def _dot(a: Vec, b: Vec) -> float: return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def _norm(a: Vec) -> float: return math.sqrt(_dot(a, a))
def _dist(a: Vec, b: Vec) -> float: return _norm(_sub(a, b))


def _centroid(pts: List[Vec]) -> Vec:
    n = len(pts)
    return (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n, sum(p[2] for p in pts) / n)


def _dedupe(verts: List[Vec], tol: float = 1e-6) -> List[Vec]:
    """Drop consecutive (and wrap-around) duplicate vertices."""
    out: List[Vec] = []
    for v in verts:
        if not out or _dist(v, out[-1]) > tol:
            out.append(v)
    if len(out) > 1 and _dist(out[0], out[-1]) <= tol:
        out.pop()
    return out


def _coord_key(v: Vec, tol: float) -> Tuple[int, int, int]:
    inv = 1.0 / tol
    return (round(v[0] * inv), round(v[1] * inv), round(v[2] * inv))


# ---------- pass 1: merge near-coincident vertices ----------
def snap_vertices(facets: List[PlainFacet], tol: float = DEFAULT_SNAP) -> List[PlainFacet]:
    clusters: List[List[Vec]] = []
    centroids: List[Vec] = []

    def assign(v: Vec) -> int:
        best, bd = -1, tol
        for i, c in enumerate(centroids):
            d = _dist(v, c)
            if d <= bd:
                bd, best = d, i
        return best

    for f in facets:
        for v in f["verts"]:  # type: ignore[union-attr]
            i = assign(v)
            if i < 0:
                clusters.append([v])
                centroids.append(v)
            else:
                clusters[i].append(v)
                centroids[i] = _centroid(clusters[i])

    def snap(v: Vec) -> Vec:
        best, bd = v, 1e18
        for c in centroids:
            d = _dist(v, c)
            if d < bd:
                bd, best = d, c
        return best

    out: List[PlainFacet] = []
    for f in facets:
        snapped = [snap(v) for v in f["verts"]]  # type: ignore[union-attr]
        out.append({"id": f["id"], "verts": _dedupe(snapped)})
    return out


# ---------- pass 2: T-junction resolution ----------
def _on_segment(p: Vec, a: Vec, b: Vec, tol: float) -> bool:
    ab = _sub(b, a)
    L2 = _dot(ab, ab)
    if L2 == 0:
        return _dist(p, a) <= tol
    t = _dot(_sub(p, a), ab) / L2
    if t < -1e-9 or t > 1 + 1e-9:
        return False
    proj = (a[0] + ab[0] * t, a[1] + ab[1] * t, a[2] + ab[2] * t)
    return _dist(p, proj) <= tol


def resolve_t_junctions(facets: List[PlainFacet], tol: float = DEFAULT_ON_EDGE) -> List[PlainFacet]:
    all_pts: List[Vec] = []
    for f in facets:
        all_pts.extend(f["verts"])  # type: ignore[union-attr]

    out: List[PlainFacet] = []
    for f in facets:
        verts: List[Vec] = list(f["verts"])  # type: ignore[arg-type]
        n = len(verts)
        new: List[Vec] = []
        for i in range(n):
            a, b = verts[i], verts[(i + 1) % n]
            new.append(a)
            on = [
                p for p in all_pts
                if _dist(p, a) > tol and _dist(p, b) > tol and _on_segment(p, a, b, tol)
            ]
            on.sort(key=lambda p: _dist(p, a))
            for p in on:
                if not new or _dist(p, new[-1]) > tol:
                    new.append(p)
        out.append({"id": f["id"], "verts": _dedupe(new)})
    return out


# ---------- pass 3: collinear cleanup (junction-aware) ----------
def drop_collinear(facets: List[PlainFacet], angle_tol_deg: float = 2.0,
                   snap_tol: float = DEFAULT_SNAP) -> List[PlainFacet]:
    # degree of each vertex location = how many facets touch it
    degree: Dict[Tuple[int, int, int], int] = {}
    for f in facets:
        seen = {_coord_key(v, snap_tol) for v in f["verts"]}  # type: ignore[union-attr]
        for k in seen:
            degree[k] = degree.get(k, 0) + 1

    out: List[PlainFacet] = []
    for f in facets:
        verts: List[Vec] = list(f["verts"])  # type: ignore[arg-type]
        n = len(verts)
        keep: List[Vec] = []
        for i in range(n):
            prev, cur, nxt = verts[(i - 1) % n], verts[i], verts[(i + 1) % n]
            shared = degree.get(_coord_key(cur, snap_tol), 0) > 1
            v1, v2 = _sub(cur, prev), _sub(nxt, cur)
            if _norm(v1) < 1e-9 or _norm(v2) < 1e-9:
                continue
            cosang = max(-1.0, min(1.0, _dot(v1, v2) / (_norm(v1) * _norm(v2))))
            ang = math.degrees(math.acos(cosang))
            if shared or ang > angle_tol_deg:  # keep corners and shared/junction points
                keep.append(cur)
        out.append({"id": f["id"], "verts": keep})
    return out


def snap_model(facets: List[PlainFacet], snap_tol: float = DEFAULT_SNAP,
               edge_tol: float = DEFAULT_ON_EDGE) -> List[PlainFacet]:
    f = snap_vertices(facets, snap_tol)
    f = resolve_t_junctions(f, edge_tol)
    f = drop_collinear(f, snap_tol=snap_tol)
    return f


# ---------- interop with roofwall.measurement.edges ----------
def from_roof_edges(facets) -> List[PlainFacet]:
    return [{"id": f.id, "verts": list(f.verts)} for f in facets]


def to_roof_edges(facets: List[PlainFacet]):
    from roofwall.measurement.edges import make_facet  # local import to avoid cycles
    return [make_facet(f["id"], list(f["verts"]), source=str(f.get("source", "geometry")))
            for f in facets]  # type: ignore[arg-type]


def weld(facets, *, snap_tol: float = DEFAULT_SNAP, edge_tol: float = DEFAULT_ON_EDGE):
    """Snap a list of EdgeFacets and return welded EdgeFacets (round-trips dicts)."""
    plain = snap_model(from_roof_edges(facets), snap_tol=snap_tol, edge_tol=edge_tol)
    return to_roof_edges(plain)

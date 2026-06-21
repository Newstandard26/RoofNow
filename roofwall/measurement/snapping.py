"""Shared-edge snapping — weld independently-traced facet polygons.

This is the linchpin between boundary recovery and ``edges`` classification.
``classify_edges`` only recognizes a shared edge when **both** facets use the
same endpoint coordinates (within ~0.05 ft). Polygons traced independently
(from a DSM raster, a point cloud, etc.) never line up exactly, so without
this step every shared edge reads as two boundary edges — ridges/hips/valleys
vanish and eaves/rakes explode.

``weld`` makes facets share endpoints in three steps (spec order):
  1. Global vertex merge — cluster all vertices within ``merge_tol`` and
     replace each cluster with its centroid.
  2. T-junction resolution — where a vertex of facet A lies on an *edge* of
     facet B, insert it into B so the two facets share it.
  3. Collinear cleanup — drop redundant near-collinear vertices, but never
     ones shared with another facet (those are real corners / T-junctions).

Operates on :class:`roofwall.measurement.edges.EdgeFacet` and returns rebuilt
facets (normals/centroids recomputed). Pure Python, no external deps.
"""

from __future__ import annotations

import math
from typing import List, Sequence

from roofwall.measurement.edges import EdgeFacet, Vec, make_facet

MERGE_TOL = 0.25       # ft — vertex clustering radius
TJUNCTION_TOL = 0.05   # ft — how close a vertex must be to an edge to split it
COLLINEAR_TOL = 0.03   # ft — perpendicular slack for "redundant" vertices


# ---------- small vector helpers ----------
def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _dist(a: Vec, b: Vec) -> float:
    return math.sqrt(_dot(_sub(a, b), _sub(a, b)))


def _add_scaled(a: Vec, ab: Vec, t: float) -> Vec:
    return (a[0] + ab[0] * t, a[1] + ab[1] * t, a[2] + ab[2] * t)


def _project_param(p: Vec, a: Vec, b: Vec) -> float:
    """Parameter t of p's projection onto segment a->b (unclamped)."""
    ab = _sub(b, a)
    denom = _dot(ab, ab)
    if denom == 0:
        return 0.0
    return _dot(_sub(p, a), ab) / denom


def _point_segment_distance(p: Vec, a: Vec, b: Vec) -> float:
    t = max(0.0, min(1.0, _project_param(p, a, b)))
    return _dist(p, _add_scaled(a, _sub(b, a), t))


# --------------------------------------------------------------------------
# 1. Global vertex merge
# --------------------------------------------------------------------------


def merge_vertices(facets: Sequence[EdgeFacet], tol: float = MERGE_TOL) -> List[EdgeFacet]:
    """Cluster all vertices within ``tol`` and snap each to its cluster centroid."""
    # Gather every vertex with a back-reference to (facet, position).
    refs: list[tuple[int, int, Vec]] = []
    for fi, f in enumerate(facets):
        for vi, v in enumerate(f.verts):
            refs.append((fi, vi, v))

    # Greedy clustering: each vertex joins the first cluster whose running
    # centroid is within tol, else starts a new one.
    centroids: list[Vec] = []
    sums: list[list[float]] = []
    counts: list[int] = []
    assign: list[int] = []
    for _, _, v in refs:
        ci = -1
        for i, c in enumerate(centroids):
            if _dist(v, c) <= tol:
                ci = i
                break
        if ci == -1:
            ci = len(centroids)
            centroids.append(v)
            sums.append([v[0], v[1], v[2]])
            counts.append(1)
        else:
            sums[ci][0] += v[0]
            sums[ci][1] += v[1]
            sums[ci][2] += v[2]
            counts[ci] += 1
            centroids[ci] = (sums[ci][0] / counts[ci], sums[ci][1] / counts[ci],
                             sums[ci][2] / counts[ci])
        assign.append(ci)

    final = [(s[0] / n, s[1] / n, s[2] / n) for s, n in zip(sums, counts)]

    new_verts: list[list[Vec]] = [list(f.verts) for f in facets]
    for k, (fi, vi, _) in enumerate(refs):
        new_verts[fi][vi] = final[assign[k]]

    return [make_facet(f.id, new_verts[fi], source=f.source)
            for fi, f in enumerate(facets)]


# --------------------------------------------------------------------------
# 2. T-junction resolution
# --------------------------------------------------------------------------


def resolve_t_junctions(
    facets: Sequence[EdgeFacet], tol: float = TJUNCTION_TOL
) -> List[EdgeFacet]:
    """Insert a vertex of facet A that lies on facet B's edge into B's ring."""
    # Distinct vertices across all facets (snapped points are equal).
    all_verts: list[Vec] = []
    for f in facets:
        for v in f.verts:
            if not any(_dist(v, u) <= tol for u in all_verts):
                all_verts.append(v)

    new_facets: list[EdgeFacet] = []
    for f in facets:
        ring = list(f.verts)
        out: list[Vec] = []
        n = len(ring)
        for i in range(n):
            a = ring[i]
            b = ring[(i + 1) % n]
            out.append(a)
            seg_len = _dist(a, b)
            if seg_len < tol:
                continue
            # Candidate vertices lying strictly inside this edge.
            on_edge: list[tuple[float, Vec]] = []
            for v in all_verts:
                if _dist(v, a) <= tol or _dist(v, b) <= tol:
                    continue
                t = _project_param(v, a, b)
                if tol / seg_len < t < 1.0 - tol / seg_len and \
                        _point_segment_distance(v, a, b) <= tol:
                    on_edge.append((t, v))
            for _, v in sorted(on_edge, key=lambda x: x[0]):
                out.append(v)
        new_facets.append(make_facet(f.id, out, source=f.source))
    return new_facets


# --------------------------------------------------------------------------
# 3. Collinear cleanup (preserving shared / T-junction vertices)
# --------------------------------------------------------------------------


def drop_collinear(
    facets: Sequence[EdgeFacet],
    tol: float = COLLINEAR_TOL,
    *,
    protect_shared: bool = True,
) -> List[EdgeFacet]:
    """Remove redundant near-collinear vertices, keeping shared corners."""
    # A vertex shared by >1 facet is a real corner/T-junction — never drop it.
    shared: list[Vec] = []
    if protect_shared:
        seen: list[tuple[Vec, int]] = []
        for f in facets:
            counted: list[Vec] = []
            for v in f.verts:
                if any(_dist(v, c) <= MERGE_TOL for c in counted):
                    continue
                counted.append(v)
                hit = next((i for i, (u, _) in enumerate(seen) if _dist(v, u) <= MERGE_TOL), -1)
                if hit == -1:
                    seen.append((v, 1))
                else:
                    seen[hit] = (seen[hit][0], seen[hit][1] + 1)
        shared = [u for u, c in seen if c > 1]

    def is_protected(v: Vec) -> bool:
        return any(_dist(v, s) <= MERGE_TOL for s in shared)

    new_facets: list[EdgeFacet] = []
    for f in facets:
        ring = list(f.verts)
        keep = [True] * len(ring)
        n = len(ring)
        for i in range(n):
            prev = ring[(i - 1) % n]
            cur = ring[i]
            nxt = ring[(i + 1) % n]
            if is_protected(cur):
                continue
            if _point_segment_distance(cur, prev, nxt) <= tol:
                keep[i] = False
        cleaned = [v for v, k in zip(ring, keep) if k]
        if len(cleaned) < 3:
            cleaned = ring  # never collapse a facet
        new_facets.append(make_facet(f.id, cleaned, source=f.source))
    return new_facets


# --------------------------------------------------------------------------
# Orchestrator
# --------------------------------------------------------------------------


def weld(
    facets: Sequence[EdgeFacet],
    *,
    merge_tol: float = MERGE_TOL,
    tjunction_tol: float = TJUNCTION_TOL,
    collinear_tol: float = COLLINEAR_TOL,
) -> List[EdgeFacet]:
    """Run merge -> T-junction -> collinear so facets share exact endpoints."""
    f = merge_vertices(facets, merge_tol)
    f = resolve_t_junctions(f, tjunction_tol)
    f = drop_collinear(f, collinear_tol)
    return f

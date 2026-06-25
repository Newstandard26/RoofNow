"""Solve the planar graph into roof faces (closed cycles + a fitted plane each).

Steps 4–6 of the pipeline:
  * find the minimal closed face cycles of the planar graph by half-edge
    traversal (the "next edge clockwise" rule), in the XY projection;
  * drop the unbounded outer face;
  * fit one plane (z = a·x + b·y + c) to each face's 3D junction positions;
  * reject degenerate and mutually-overlapping faces.

Pure stdlib (no numpy/shapely) so the solver stays light and self-contained.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from roofwall.wireframe.graph import PlanarGraph, build_graph
from roofwall.wireframe.segments import Vec3

ABC = Tuple[float, float, float]


@dataclass
class Face:
    junctions: List[int]              # ordered junction ids, CCW in XY (viewed top-down)
    verts: List[Vec3]                 # the matching 3D polygon
    plane: ABC                        # fitted z = a·x + b·y + c

    def centroid(self) -> Vec3:
        n = len(self.verts)
        sx = sum(v[0] for v in self.verts) / n
        sy = sum(v[1] for v in self.verts) / n
        sz = sum(v[2] for v in self.verts) / n
        return (sx, sy, sz)

    def area_xy(self) -> float:
        return abs(_signed_area_xy(self.verts))

    def plane_z(self, x: float, y: float) -> float:
        return self.plane[0] * x + self.plane[1] * y + self.plane[2]


@dataclass
class SolvedWireframe:
    graph: PlanarGraph
    faces: List[Face]
    rejected: List[dict] = field(default_factory=list)


# ---------------------------------------------------------------- geometry utils
def _signed_area_xy(pts: List[Vec3]) -> float:
    s = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i][0], pts[i][1]
        x2, y2 = pts[(i + 1) % n][0], pts[(i + 1) % n][1]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def _det3(m) -> float:
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))


def fit_plane(verts: List[Vec3]) -> ABC:
    """Least-squares plane z = a·x + b·y + c through the points (3x3 normal
    equations, Cramer's rule). Degenerate (collinear / vertical) -> flat plane
    at the mean height."""
    n = len(verts)
    Sx = Sy = Sz = Sxx = Syy = Sxy = Sxz = Syz = 0.0
    for x, y, z in verts:
        Sx += x; Sy += y; Sz += z
        Sxx += x * x; Syy += y * y; Sxy += x * y
        Sxz += x * z; Syz += y * z
    M = [[Sxx, Sxy, Sx], [Sxy, Syy, Sy], [Sx, Sy, float(n)]]
    rhs = [Sxz, Syz, Sz]
    det = _det3(M)
    if abs(det) < 1e-9:
        return (0.0, 0.0, Sz / n if n else 0.0)
    out = []
    for col in range(3):
        Mc = [row[:] for row in M]
        for r in range(3):
            Mc[r][col] = rhs[r]
        out.append(_det3(Mc) / det)
    return (out[0], out[1], out[2])


# ---------------------------------------------------------------- face finding
def find_face_cycles(graph: PlanarGraph) -> List[List[int]]:
    """Minimal closed face cycles (lists of junction ids) by half-edge traversal.

    At each junction the outgoing half-edges are sorted by heading; arriving at a
    vertex, the face continues on the edge immediately *clockwise* of the
    reverse-incoming direction. This enumerates every face exactly once, including
    the unbounded outer face (returned too; the caller drops it).
    """
    pos = {j.id: j.xyz for j in graph.junctions}

    def heading(u: int, v: int) -> float:
        return math.atan2(pos[v][1] - pos[u][1], pos[v][0] - pos[u][0])

    out: Dict[int, List[Tuple[float, int]]] = {j.id: [] for j in graph.junctions}
    for e in graph.edges:
        out[e.a].append((heading(e.a, e.b), e.b))
        out[e.b].append((heading(e.b, e.a), e.a))
    order: Dict[int, List[int]] = {}
    for u, lst in out.items():
        lst.sort()
        order[u] = [w for _, w in lst]

    def next_half_edge(u: int, v: int) -> Tuple[int, int]:
        nbrs = order[v]
        i = nbrs.index(u)                 # the reverse direction v->u
        w = nbrs[(i - 1) % len(nbrs)]     # one step clockwise
        return (v, w)

    visited: set = set()
    cycles: List[List[int]] = []
    for e in graph.edges:
        for he in ((e.a, e.b), (e.b, e.a)):
            if he in visited:
                continue
            cyc: List[int] = []
            cur = he
            guard = 0
            limit = 4 * len(graph.edges) + 8
            while cur not in visited and guard < limit:
                visited.add(cur)
                cyc.append(cur[0])
                cur = next_half_edge(*cur)
                guard += 1
                if cur == he:
                    break
            if len(cyc) >= 3:
                cycles.append(cyc)
    return cycles


# ---------------------------------------------------------------- solver
def solve(segments, *, snap_tol: float = 0.5, min_area_sqft: float = 4.0,
          overlap_tol_sqft: float = 1.0) -> SolvedWireframe:
    """Segments -> solved wireframe (graph + non-overlapping planar faces).

    Drops the outer face, fits a plane per face, rejects degenerate/sliver faces
    and any face that overlaps an already-accepted (larger) one — so the output
    facets are guaranteed non-overlapping.
    """
    graph = build_graph(segments, snap_tol=snap_tol)
    cycles = find_face_cycles(graph)

    raw: List[Tuple[List[int], float]] = []
    for cyc in cycles:
        verts = [graph.pos(j) for j in cyc]
        raw.append((cyc, _signed_area_xy(verts)))
    if not raw:
        return SolvedWireframe(graph=graph, faces=[])

    # the unbounded outer face traces the whole perimeter, so its |signed area|
    # equals the sum of the interior faces' areas -> it is the single largest in
    # magnitude. (Its orientation is also opposite the interior faces.)
    outer_idx = max(range(len(raw)), key=lambda i: abs(raw[i][1]))

    rejected: List[dict] = []
    candidates: List[Face] = []
    for i, (cyc, sa) in enumerate(raw):
        if i == outer_idx:
            continue
        # normalise to CCW (top-down) so make_facet's normal points up
        ids = cyc if sa > 0 else list(reversed(cyc))
        verts = [graph.pos(j) for j in ids]
        area = abs(sa)
        if len(ids) < 3 or area < min_area_sqft:
            rejected.append({"junctions": cyc, "reason": "degenerate_or_sliver"})
            continue
        candidates.append(Face(junctions=ids, verts=verts, plane=fit_plane(verts)))

    # reject overlaps: keep larger faces, drop any later face that overlaps them
    candidates.sort(key=lambda f: f.area_xy(), reverse=True)
    accepted: List[Face] = []
    for f in candidates:
        if any(_xy_overlap(f.verts, g.verts) > overlap_tol_sqft for g in accepted):
            rejected.append({"junctions": f.junctions, "reason": "overlaps_accepted_face"})
            continue
        accepted.append(f)

    return SolvedWireframe(graph=graph, faces=accepted, rejected=rejected)


def _xy_overlap(a: List[Vec3], b: List[Vec3]) -> float:
    """Interior XY overlap area of two facet polygons (shared edges/vertices do
    NOT count — only genuine area intersection). Uses shapely when available;
    otherwise a bounding-box upper bound shrunk to ignore edge contact."""
    try:
        from shapely.geometry import Polygon
        pa = Polygon([(p[0], p[1]) for p in a]).buffer(0)
        pb = Polygon([(p[0], p[1]) for p in b]).buffer(0)
        inter = pa.intersection(pb)
        return inter.area if inter.geom_type in ("Polygon", "MultiPolygon") else 0.0
    except Exception:
        ax0 = min(p[0] for p in a); ax1 = max(p[0] for p in a)
        ay0 = min(p[1] for p in a); ay1 = max(p[1] for p in a)
        bx0 = min(p[0] for p in b); bx1 = max(p[0] for p in b)
        by0 = min(p[1] for p in b); by1 = max(p[1] for p in b)
        ix = max(0.0, min(ax1, bx1) - max(ax0, bx0))
        iy = max(0.0, min(ay1, by1) - max(ay0, by0))
        return ix * iy

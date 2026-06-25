"""Planar junction/edge graph built from snapped line segments.

Step 2–3 of the wireframe pipeline: snap segment endpoints that coincide (within
``snap_tol``) into shared junctions, then build the undirected planar graph
(deduplicated edges, zero-length dropped). The junction positions are the 3D
average of the endpoints that snapped together, so the graph carries height.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Sequence, Set, Tuple

from roofwall.wireframe.segments import Segment, Vec3


@dataclass
class Junction:
    id: int
    xyz: Vec3


@dataclass(frozen=True)
class GraphEdge:
    a: int   # junction id, always a < b
    b: int


@dataclass
class PlanarGraph:
    junctions: List[Junction]
    edges: List[GraphEdge]

    def pos(self, jid: int) -> Vec3:
        return self.junctions[jid].xyz

    def adjacency(self) -> Dict[int, Set[int]]:
        adj: Dict[int, Set[int]] = {j.id: set() for j in self.junctions}
        for e in self.edges:
            adj[e.a].add(e.b)
            adj[e.b].add(e.a)
        return adj


def build_graph(segments: Sequence[Segment], *, snap_tol: float = 0.5) -> PlanarGraph:
    """Snap endpoints into junctions and assemble the undirected planar graph.

    Endpoints within ``snap_tol`` of an existing junction merge into it (the
    junction position becomes the running 3D average); otherwise a new junction
    is created. Each segment contributes one undirected edge between its two
    junctions; degenerate (same-junction) and duplicate edges are dropped.
    """
    centers: List[List[float]] = []
    counts: List[int] = []

    def find_or_add(p: Vec3) -> int:
        best, best_d = -1, snap_tol
        for i, c in enumerate(centers):
            d = math.dist(p, c)
            if d <= best_d:
                best, best_d = i, d
        if best < 0:
            centers.append([float(p[0]), float(p[1]), float(p[2])])
            counts.append(1)
            return len(centers) - 1
        n = counts[best]
        centers[best] = [(centers[best][k] * n + p[k]) / (n + 1) for k in range(3)]
        counts[best] = n + 1
        return best

    seg_js: List[Tuple[int, int]] = []
    for s in segments:
        seg_js.append((find_or_add(s.p0), find_or_add(s.p1)))

    junctions = [Junction(i, (c[0], c[1], c[2])) for i, c in enumerate(centers)]
    eset: Dict[Tuple[int, int], GraphEdge] = {}
    for j0, j1 in seg_js:
        if j0 == j1:
            continue
        a, b = (j0, j1) if j0 < j1 else (j1, j0)
        eset[(a, b)] = GraphEdge(a, b)
    return PlanarGraph(junctions=junctions, edges=list(eset.values()))

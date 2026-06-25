"""Line segments — the input to the roof wireframe solver.

Phase 1 is synthetic: the solver takes a set of candidate roof line *segments*
(3D endpoints, with optional type hints from upstream edge detection / Solar
priors) and reconstructs clean facets from the solved junction/face graph. It
never traces DSM label blobs or uses Solar bounding boxes as final polygons.

``segments_from_facets`` derives a segment set from known facets so the solver
can be exercised end-to-end without DSM/imagery.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple

Vec3 = Tuple[float, float, float]


@dataclass(frozen=True)
class Segment:
    """A candidate roof line segment with 3D endpoints.

    ``type_candidates`` are *advisory* hints (ridge/hip/valley/eave/rake) from
    upstream detection; the solver classifies edges from the solved topology, not
    from these, so a wrong hint cannot corrupt the diagram.
    """

    p0: Vec3
    p1: Vec3
    type_candidates: Tuple[str, ...] = ()

    def length(self) -> float:
        return math.dist(self.p0, self.p1)

    def midpoint(self) -> Vec3:
        return tuple((a + b) / 2.0 for a, b in zip(self.p0, self.p1))  # type: ignore[return-value]


def _quant_key(p: Vec3, q: float) -> Tuple[int, int, int]:
    return (round(p[0] / q), round(p[1] / q), round(p[2] / q))


def _edge_key(a: Vec3, b: Vec3, q: float):
    ka, kb = _quant_key(a, q), _quant_key(b, q)
    return (ka, kb) if ka <= kb else (kb, ka)


def segments_from_facets(facets, *, quant: float = 0.05) -> List[Segment]:
    """Build the synthetic segment set from known facets.

    Every facet boundary edge becomes one candidate :class:`Segment`; an edge
    shared by two facets is emitted once (deduplicated on quantised endpoints).
    Accepts ``EdgeFacet``-like objects (``.verts``) or ``{"verts": [...]}`` dicts.
    Simulates the output of edge/line detection for testing the solver.
    """
    seen: Dict[object, Tuple[Vec3, Vec3]] = {}
    for f in facets:
        verts = list(f.verts) if hasattr(f, "verts") else list(f["verts"])
        n = len(verts)
        for i in range(n):
            a = tuple(float(c) for c in verts[i])
            b = tuple(float(c) for c in verts[(i + 1) % n])
            if math.dist(a, b) < quant:
                continue
            seen.setdefault(_edge_key(a, b, quant), (a, b))  # type: ignore[arg-type]
    return [Segment(p0=a, p1=b) for a, b in seen.values()]

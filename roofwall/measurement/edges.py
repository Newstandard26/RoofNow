"""Ridge / hip / valley / eave / rake extraction from a 3D roof model.

Python port of the validated ``roofEdges.ts`` prototype (kept in sync with
``web/roofEdges.ts`` + its vitest suite). This is the "Total Line Lengths"
piece — the EagleView Length Diagram — that the report was missing.

INPUT: a roof as planar facets, each a list of 3D vertices ``(x, y, z)`` in
feet (z = height). Facet polygons come from LiDAR plane segmentation, a 3D
reconstruction, or Solar segments after recovering boundaries from the DSM.

OUTPUT: every edge classified, with true (3D) lengths summed per type.

CLASSIFICATION
  Boundary edge (1 facet):  level -> EAVE,  sloped -> RAKE
  Shared edge   (2 facets):  level -> RIDGE
                             sloped -> HIP    (convex fold, sheds water out)
                                       VALLEY (concave fold, internal channel)
  Hip vs valley: sign of the neighbor facet's centroid vs this facet's plane
  — below the plane => convex => hip; above => concave => valley.

The :class:`EdgeFacet` lines up with the engine's facet representation
(:class:`roofwall.measurement.engine.FacetMeasurement`): it exposes the same
``pitch`` (an engine :class:`Pitch`), ``azimuth_deg`` (downslope heading,
0=N clockwise — matching the LiDAR/Solar convention) and ``source`` so the
geometric facet and the measured facet describe the same surface.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from roofwall.measurement.engine import Pitch

Vec = Tuple[float, float, float]

# Tolerances (feet)
SNAP = 0.05      # vertex coincidence for shared-edge matching (~5/8")
LEVEL_DZ = 0.25  # |dz| below this => edge is "level"

EDGE_KINDS = ("eave", "rake", "ridge", "hip", "valley", "junction")


# ---------- vector helpers ----------
def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _scale(a: Vec, s: float) -> Vec:
    return (a[0] * s, a[1] * s, a[2] * s)


def _norm_len(a: Vec) -> float:
    return math.sqrt(_dot(a, a))


def _dist(a: Vec, b: Vec) -> float:
    return _norm_len(_sub(a, b))


def newell_normal(verts: List[Vec]) -> Vec:
    """Robust polygon normal (Newell's method), oriented up (z >= 0)."""
    nx = ny = nz = 0.0
    n = len(verts)
    for i in range(n):
        cx, cy, cz = verts[i]
        dx, dy, dz = verts[(i + 1) % n]
        nx += (cy - dy) * (cz + dz)
        ny += (cz - dz) * (cx + dx)
        nz += (cx - dx) * (cy + dy)
    length = _norm_len((nx, ny, nz))
    if length == 0:
        return (0.0, 0.0, 1.0)
    nrm = (nx / length, ny / length, nz / length)
    return nrm if nrm[2] >= 0 else _scale(nrm, -1.0)


def centroid(verts: List[Vec]) -> Vec:
    n = len(verts)
    sx = sy = sz = 0.0
    for v in verts:
        sx += v[0]
        sy += v[1]
        sz += v[2]
    return (sx / n, sy / n, sz / n)


def _round_half_up(x: float) -> int:
    # Match JS Math.round (half-up), not Python's banker's rounding.
    return math.floor(x + 0.5)


def _key_of(p: Vec) -> str:
    inv = 1.0 / SNAP
    return f"{_round_half_up(p[0] * inv)},{_round_half_up(p[1] * inv)},{_round_half_up(p[2] * inv)}"


def _edge_key(a: Vec, b: Vec) -> str:
    ka, kb = _key_of(a), _key_of(b)
    return f"{ka}|{kb}" if ka < kb else f"{kb}|{ka}"


@dataclass
class EdgeFacet:
    """A 3D roof facet polygon, aligned with the engine's facet fields."""

    id: str
    verts: List[Vec]
    normal: Vec
    cen: Vec
    source: str = "geometry"

    @property
    def pitch_x12(self) -> float:
        nz = min(1.0, max(1e-9, abs(self.normal[2])))
        slope = math.tan(math.acos(nz))  # rise/run
        return slope * 12.0

    @property
    def pitch(self) -> Pitch:
        """Slope as the engine's :class:`Pitch` value object."""
        return Pitch.from_x12(self.pitch_x12)

    @property
    def azimuth_deg(self) -> float:
        """Downslope/facing heading (0=N, clockwise) — engine convention."""
        nx, ny = self.normal[0], self.normal[1]
        if abs(nx) < 1e-12 and abs(ny) < 1e-12:
            return 0.0
        return math.degrees(math.atan2(nx, ny)) % 360.0


def make_facet(id: str, verts: List[Vec], *, source: str = "geometry") -> EdgeFacet:
    return EdgeFacet(id=id, verts=list(verts), normal=newell_normal(verts),
                     cen=centroid(verts), source=source)


def pitch_x12(f: EdgeFacet) -> float:
    """Roof pitch as rise-in-12 for a facet (free-function form)."""
    return f.pitch_x12


@dataclass(frozen=True)
class Edge:
    a: Vec
    b: Vec
    kind: str
    length: float
    facets: Tuple[str, ...]


def _signed_height_off_plane(point: Vec, plane_pt: Vec, up_normal: Vec) -> float:
    return _dot(up_normal, _sub(point, plane_pt))


def classify_edges(facets: List[EdgeFacet]) -> List[Edge]:
    """Group facet boundary segments into shared edges and classify each."""
    groups: Dict[str, List[Tuple[Vec, Vec, EdgeFacet]]] = {}
    for f in facets:
        v = f.verts
        for i in range(len(v)):
            a = v[i]
            b = v[(i + 1) % len(v)]
            groups.setdefault(_edge_key(a, b), []).append((a, b, f))

    edges: List[Edge] = []
    for items in groups.values():
        a, b, _ = items[0]
        length = _dist(a, b)
        if length < SNAP:
            continue
        level = abs(a[2] - b[2]) <= LEVEL_DZ

        uniq: Dict[str, EdgeFacet] = {}
        for ia, ib, f in items:
            uniq[f.id] = f
        touching = list(uniq.values())
        fids = tuple(f.id for f in touching)

        if len(touching) == 1:
            kind = "eave" if level else "rake"
        elif len(touching) == 2:
            if level:
                kind = "ridge"
            else:
                fa, fb = touching
                s = _signed_height_off_plane(fb.cen, fa.verts[0], fa.normal)
                kind = "hip" if s < 0 else "valley"
        else:
            kind = "junction"
        edges.append(Edge(a=a, b=b, kind=kind, length=length, facets=fids))
    return edges


@dataclass
class TypeSummary:
    count: int = 0
    length: float = 0.0

    def __getitem__(self, key: str):
        # Allow dict-style access (s["ridge"]["count"]) as well as attributes.
        if key in ("count", "length"):
            return getattr(self, key)
        raise KeyError(key)


def summarize(edges: List[Edge]) -> Dict[str, TypeSummary]:
    out: Dict[str, TypeSummary] = {}
    for e in edges:
        s = out.setdefault(e.kind, TypeSummary())
        s.count += 1
        s.length += e.length
    return out


def line_lengths(facets: List[EdgeFacet]) -> Dict[str, TypeSummary]:
    """Convenience: facets -> summarized line lengths by edge type."""
    return summarize(classify_edges(facets))


def line_lengths_dict(facets: List[EdgeFacet]) -> Dict[str, object]:
    """JSON-friendly line-length totals incl. a drip-edge (eaves+rakes) roll-up."""
    summary = line_lengths(facets)
    out: Dict[str, object] = {}
    for kind in EDGE_KINDS:
        if kind in summary:
            out[kind] = {
                "count": summary[kind].count,
                "length_ft": round(summary[kind].length, 1),
            }
    eave = summary["eave"].length if "eave" in summary else 0.0
    rake = summary["rake"].length if "rake" in summary else 0.0
    out["drip_edge"] = {"length_ft": round(eave + rake, 1), "note": "eaves + rakes"}
    return out


# ---------------- demo roof builders (mirror the TS suite) ----------------
def hip_roof(L: float = 40, W: float = 24, pitch: float = 6) -> List[EdgeFacet]:
    run = W / 2
    h = (run * pitch) / 12
    r1: Vec = (W / 2, W / 2, h)
    r2: Vec = (L - W / 2, W / 2, h)
    c00: Vec = (0, 0, 0)
    c10: Vec = (L, 0, 0)
    c11: Vec = (L, W, 0)
    c01: Vec = (0, W, 0)
    return [
        make_facet("front", [c00, c10, r2, r1]),
        make_facet("back", [c11, c01, r1, r2]),
        make_facet("left", [c01, c00, r1]),
        make_facet("right", [c10, c11, r2]),
    ]


def gable_roof(L: float = 40, W: float = 24, pitch: float = 6) -> List[EdgeFacet]:
    h = ((W / 2) * pitch) / 12
    fr: List[Vec] = [(0, 0, 0), (L, 0, 0), (L, W / 2, h), (0, W / 2, h)]
    bk: List[Vec] = [(L, W, 0), (0, W, 0), (0, W / 2, h), (L, W / 2, h)]
    return [make_facet("front", fr), make_facet("back", bk)]


def valley_pair() -> List[EdgeFacet]:
    p0: Vec = (0, 0, 0)
    p1: Vec = (10, 10, 4)
    return [
        make_facet("A", [p0, p1, (10, 0, 4)]),
        make_facet("B", [p0, (0, 10, 4), p1]),
    ]


def cross_gable() -> List[EdgeFacet]:
    """A watertight T cross-gable: 3 ridges, 2 valleys, 5 eaves, 6 rakes.

    Main gable runs E-W (ridge y=10, z=5); a wing runs N-S (ridge x=20, z=5)
    over the main's north half, so the two roofs meet along valleys that run
    from the reentrant corners up to the ridge junction at (20, 10, 5).
    A canonical fixture for shared-edge snapping (it contains both ridges and
    valleys that vanish unless facets share exact endpoints).
    """
    return [
        make_facet("main_S", [(0, 0, 0), (40, 0, 0), (40, 10, 5), (20, 10, 5), (0, 10, 5)]),
        make_facet("main_N_left", [(0, 10, 5), (0, 20, 0), (10, 20, 0), (20, 10, 5)]),
        make_facet("main_N_right", [(20, 10, 5), (30, 20, 0), (40, 20, 0), (40, 10, 5)]),
        make_facet("wing_W", [(10, 20, 0), (10, 40, 0), (20, 40, 5), (20, 10, 5)]),
        make_facet("wing_E", [(30, 20, 0), (30, 40, 0), (20, 40, 5), (20, 10, 5)]),
    ]

"""Classify the solved wireframe's edges and emit clean BuildingModel facets.

Steps 7–8 of the pipeline. Edge classification is driven by the solved
junction/face topology + the per-face planes (never by Solar bounding boxes or
label blobs):

    boundary (1 face)  level  -> eave
    boundary (1 face)  sloped -> rake
    shared   (2 faces) level  -> ridge
    shared   (2 faces) sloped, convex  -> hip      (neighbour folds *down*)
    shared   (2 faces) sloped, concave -> valley   (neighbour folds *up*)

The facets are guaranteed non-overlapping (the solver enforces it), so the
resulting BuildingModel is a clean, presentable roof diagram.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Tuple

from roofwall.measurement.edges import LEVEL_DZ
from roofwall.model import BuildingModel, ModelFacet, Origin
from roofwall.wireframe.segments import Segment, Vec3
from roofwall.wireframe.solve import Face, SolvedWireframe, solve

EDGE_KINDS = ("ridge", "hip", "valley", "rake", "eave")


@dataclass(frozen=True)
class ClassifiedEdge:
    a: int                 # junction id
    b: int
    kind: str
    length: float
    faces: Tuple[int, ...]  # indices into solved.faces


def _consecutive_pairs(face: Face):
    js = face.junctions
    n = len(js)
    for i in range(n):
        a, b = js[i], js[(i + 1) % n]
        yield (a, b) if a < b else (b, a)


def classify_edges(solved: SolvedWireframe) -> List[ClassifiedEdge]:
    """Classify every wireframe edge from face adjacency + plane geometry."""
    faces = solved.faces
    edge_faces: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    for fi, f in enumerate(faces):
        for key in set(_consecutive_pairs(f)):
            edge_faces[key].append(fi)

    pos = {j.id: j.xyz for j in solved.graph.junctions}
    out: List[ClassifiedEdge] = []
    for (a, b), fis in edge_faces.items():
        pa, pb = pos[a], pos[b]
        length = math.dist(pa, pb)
        if length < 1e-6:
            continue
        level = abs(pa[2] - pb[2]) <= LEVEL_DZ

        if len(fis) == 1:
            kind = "eave" if level else "rake"
        elif len(fis) == 2:
            if level:
                kind = "ridge"
            else:
                fa = faces[fis[0]]
                fb = faces[fis[1]]
                cbx, cby, cbz = fb.centroid()
                # neighbour centroid below face-A's plane -> roof folds up -> hip;
                # above -> the surfaces dish down toward the line -> valley.
                kind = "hip" if cbz < fa.plane_z(cbx, cby) else "valley"
        else:
            kind = "junction"
        out.append(ClassifiedEdge(a=a, b=b, kind=kind, length=length, faces=tuple(fis)))
    return out


def line_lengths(solved: SolvedWireframe) -> Dict[str, dict]:
    """JSON-friendly line-length totals by edge type (+ drip_edge roll-up)."""
    acc: Dict[str, List[float]] = defaultdict(list)
    for e in classify_edges(solved):
        acc[e.kind].append(e.length)
    out: Dict[str, dict] = {}
    for kind in EDGE_KINDS:
        if acc.get(kind):
            out[kind] = {"count": len(acc[kind]), "length_ft": round(sum(acc[kind]), 1)}
    drip = sum(sum(acc[k]) for k in ("eave", "rake") if k in acc)
    if drip > 0:
        out["drip_edge"] = {"length_ft": round(drip, 1), "note": "eaves + rakes"}
    return out


def to_building_model(solved: SolvedWireframe, origin: Origin, *,
                      source: str = "wireframe", notes=None) -> BuildingModel:
    """Solved faces -> BuildingModel (clean, non-overlapping 3D facet polygons)."""
    facets = [ModelFacet(id=f"F{i}", verts=[tuple(v) for v in f.verts])
              for i, f in enumerate(solved.faces)]
    model = BuildingModel(facets=facets, origin=origin, source=source, notes=notes)
    model.measured_lines = line_lengths(solved)
    return model


def solve_to_model(segments: List[Segment], origin: Origin, *, snap_tol: float = 0.5,
                   source: str = "wireframe", notes=None) -> BuildingModel:
    """Convenience: segments -> solved wireframe -> BuildingModel in one call."""
    solved = solve(segments, snap_tol=snap_tol)
    return to_building_model(solved, origin, source=source, notes=notes)

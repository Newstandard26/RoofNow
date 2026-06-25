"""Roof wireframe solver.

Reconstructs a clean, non-overlapping roof diagram from candidate line segments
via a solved junction / edge / face graph — NOT by tracing DSM label blobs or
using Solar bounding boxes as final polygons.

Pipeline:
    segments  ->  build_graph (snap endpoints -> junctions)
              ->  solve (find face cycles, fit planes, reject overlaps)
              ->  classify edges (ridge/hip/valley/eave/rake)
              ->  BuildingModel facets

Phase 1 is synthetic: segments are supplied directly (e.g. derived from known
facets via ``segments_from_facets``); later phases will feed segments from
DSM + aerial-image edge detection.
"""

from roofwall.wireframe.facets import (
    ClassifiedEdge,
    classify_edges,
    line_lengths,
    solve_to_model,
    to_building_model,
)
from roofwall.wireframe.graph import GraphEdge, Junction, PlanarGraph, build_graph
from roofwall.wireframe.segments import Segment, segments_from_facets
from roofwall.wireframe.solve import Face, SolvedWireframe, fit_plane, solve

__all__ = [
    "Segment", "segments_from_facets",
    "Junction", "GraphEdge", "PlanarGraph", "build_graph",
    "Face", "SolvedWireframe", "solve", "fit_plane",
    "ClassifiedEdge", "classify_edges", "line_lengths",
    "to_building_model", "solve_to_model",
]

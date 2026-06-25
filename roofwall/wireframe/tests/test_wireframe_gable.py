"""Wireframe solver — simple gable.

A gable solved from its line segments must come back as exactly 2 clean,
non-overlapping facets with one ridge and the correct rakes/eaves — produced by
the solved junction/face graph, not by tracing blobs or Solar boxes.
"""
import math

import pytest

from roofwall.measurement.edges import gable_roof
from roofwall.measurement.edges import line_lengths as edge_line_lengths
from roofwall.model import Origin
from roofwall.wireframe import (
    classify_edges,
    line_lengths,
    segments_from_facets,
    solve,
    to_building_model,
)


def _counts(ll):
    return {k: ll.get(k, {"count": 0})["count"]
            for k in ("ridge", "hip", "valley", "rake", "eave")}


def _no_overlap(model):
    from shapely.geometry import Polygon
    polys = [Polygon([(v[0], v[1]) for v in f.verts]) for f in model.to_edge_facets()]
    assert all(p.is_valid for p in polys), "self-intersecting facet"
    ov = sum(polys[i].intersection(polys[j]).area
             for i in range(len(polys)) for j in range(i + 1, len(polys)))
    return ov


def test_gable_solves_to_two_clean_facets():
    segs = segments_from_facets(gable_roof(40, 24, 6))
    solved = solve(segs)

    # a solved planar graph, not a blob trace
    assert len(solved.graph.junctions) == 6
    assert len(solved.graph.edges) == 7
    assert len(solved.faces) == 2
    assert solved.rejected == []

    c = _counts(line_lengths(solved))
    assert c["ridge"] == 1
    assert c["hip"] == 0 and c["valley"] == 0
    assert c["rake"] == 4            # two sloped rakes per gable end
    assert c["eave"] == 2            # two long eaves

    # one plane per face, and the two planes face opposite ways (front/back)
    assert len({round(f.plane[1], 3) for f in solved.faces}) == 2

    model = to_building_model(solved, Origin(0, 0))
    assert len(model.facets) == 2
    assert _no_overlap(model) < 1e-6

    # cross-check: the existing edge classifier agrees on the solved model
    base = {k: v.count for k, v in edge_line_lengths(model.to_edge_facets()).items()}
    assert base.get("ridge") == 1 and base.get("rake") == 4 and base.get("eave") == 2


def test_gable_ridge_is_level_and_centered():
    solved = solve(segments_from_facets(gable_roof(40, 24, 6)))
    ridge = [e for e in classify_edges(solved) if e.kind == "ridge"]
    assert len(ridge) == 1
    pa = solved.graph.pos(ridge[0].a)
    pb = solved.graph.pos(ridge[0].b)
    assert abs(pa[2] - pb[2]) < 1e-6            # level
    assert math.isclose(ridge[0].length, 40.0, rel_tol=1e-6)

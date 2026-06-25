"""Wireframe solver — cross gable with valleys.

The canonical shared-edge case: two gable wings meeting in a T. The solver must
recover 5 clean, non-overlapping facets and detect the two valleys at the
reentrant corners (the artifact the old blob pipeline could not get right),
without any eave/rake explosion.
"""
import pytest

from roofwall.measurement.edges import cross_gable
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


def _overlap(model):
    from shapely.geometry import Polygon
    polys = [Polygon([(v[0], v[1]) for v in f.verts]) for f in model.to_edge_facets()]
    assert all(p.is_valid for p in polys)
    return sum(polys[i].intersection(polys[j]).area
               for i in range(len(polys)) for j in range(i + 1, len(polys)))


def test_cross_gable_detects_valleys():
    segs = segments_from_facets(cross_gable())
    solved = solve(segs)

    assert len(solved.faces) == 5
    assert solved.rejected == []

    c = _counts(line_lengths(solved))
    assert c["valley"] == 2            # the two reentrant valleys are found
    assert c["ridge"] == 3
    assert c["hip"] == 0
    assert c["rake"] == 6
    assert c["eave"] == 5
    # no eave/rake explosion from unsnapped shared edges
    assert c["eave"] + c["rake"] <= 4 * len(solved.faces)


def test_cross_gable_clean_non_overlapping_model():
    solved = solve(segments_from_facets(cross_gable()))
    model = to_building_model(solved, Origin(0, 0))
    assert len(model.facets) == 5
    assert _overlap(model) < 1e-6

    base = {k: v.count for k, v in edge_line_lengths(model.to_edge_facets()).items()}
    assert base.get("valley") == 2 and base.get("ridge") == 3


def test_cross_gable_valleys_are_sloped_and_concave():
    solved = solve(segments_from_facets(cross_gable()))
    valleys = [e for e in classify_edges(solved) if e.kind == "valley"]
    assert len(valleys) == 2
    for e in valleys:
        pa = solved.graph.pos(e.a)
        pb = solved.graph.pos(e.b)
        assert abs(pa[2] - pb[2]) > 0.25        # a valley runs sloped (not level)

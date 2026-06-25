"""Wireframe solver — simple hip.

A hip solved from its segments must come back as 4 clean, non-overlapping facets
with one ridge, four hips, four eaves and — critically — NO false valleys.
"""
import pytest

from roofwall.measurement.edges import hip_roof
from roofwall.measurement.edges import line_lengths as edge_line_lengths
from roofwall.model import Origin
from roofwall.wireframe import (
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


def test_hip_solves_to_four_facets_no_false_valleys():
    segs = segments_from_facets(hip_roof(40, 24, 6))
    solved = solve(segs)

    assert len(solved.graph.junctions) == 6
    assert len(solved.faces) == 4
    assert solved.rejected == []

    c = _counts(line_lengths(solved))
    assert c["ridge"] == 1
    assert c["hip"] == 4
    assert c["valley"] == 0            # a hip roof has NO valleys
    assert c["rake"] == 0             # and no rakes
    assert c["eave"] == 4

    model = to_building_model(solved, Origin(0, 0))
    assert len(model.facets) == 4
    assert _overlap(model) < 1e-6

    # two of the four facets are triangular end hips (3 verts), not bbox rectangles
    tri = [f for f in solved.faces if len(f.junctions) == 3]
    assert len(tri) == 2

    base = {k: v.count for k, v in edge_line_lengths(model.to_edge_facets()).items()}
    assert base.get("ridge") == 1 and base.get("hip") == 4
    assert "valley" not in base and "rake" not in base


def test_hip_reaches_correct_ridge_and_eave_heights():
    solved = solve(segments_from_facets(hip_roof(40, 24, 6)))
    zmax = max(v[2] for f in solved.faces for v in f.verts)
    zmin = min(v[2] for f in solved.faces for v in f.verts)
    assert abs(zmax - 6.0) < 1e-6      # ridge height = (W/2)*pitch/12 = 12*6/12
    assert abs(zmin - 0.0) < 1e-6      # eaves at the wall plate

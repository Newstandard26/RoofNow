"""Shared-edge snapping — the linchpin that makes traced facets share edges.

The headline test asserts that a known cross-gable, once its facets are traced
independently (jittered, no shared endpoints), recovers its shared ridge /
valley edges after welding — and that boundary eaves collapse back to the true
perimeter count.
"""

import random

import pytest

from roofwall.measurement.edges import (
    EdgeFacet,
    cross_gable,
    gable_roof,
    line_lengths,
    make_facet,
    valley_pair,
)
from roofwall.measurement.snapping import (
    drop_collinear,
    merge_vertices,
    resolve_t_junctions,
    weld,
)


def _shatter(facets, jitter=0.08, seed=1):
    """Re-trace each facet independently: jitter every vertex < merge tol."""
    rng = random.Random(seed)
    out = []
    for f in facets:
        verts = [
            (x + rng.uniform(-jitter, jitter),
             y + rng.uniform(-jitter, jitter),
             z + rng.uniform(-jitter, jitter))
            for x, y, z in f.verts
        ]
        out.append(make_facet(f.id, verts, source=f.source))
    return out


def _counts(facets):
    return {k: v.count for k, v in line_lengths(facets).items()}


# -------------------- headline: cross-gable --------------------


def test_cross_gable_shared_edges_vanish_without_snapping():
    shattered = _shatter(cross_gable())
    c = _counts(shattered)
    # Every shared edge is misread as two boundary edges.
    assert "ridge" not in c
    assert "valley" not in c
    assert c["eave"] > 5  # eaves exploded beyond the true perimeter


def test_cross_gable_weld_recovers_ridges_and_valleys():
    golden = cross_gable()
    gold = _counts(golden)
    welded = weld(_shatter(golden))
    got = _counts(welded)

    # Golden topology: 3 ridges, 2 valleys, 5 eaves, 6 rakes.
    assert gold == {"eave": 5, "rake": 6, "ridge": 3, "valley": 2}
    # Welding the independently-traced facets reproduces it exactly.
    assert got == gold
    # Boundary eaves == true perimeter eave count (no shared edge leaked in).
    assert got["eave"] == gold["eave"]


def test_cross_gable_weld_lengths_close_to_golden():
    golden = cross_gable()
    g = line_lengths(golden)
    w = line_lengths(weld(_shatter(golden)))
    for kind in ("ridge", "valley", "eave", "rake"):
        assert abs(w[kind].length - g[kind].length) < 1.0  # within 1 ft


# -------------------- component steps --------------------


def test_merge_recovers_gable_ridge():
    shattered = _shatter(gable_roof(40, 24, 6))
    assert "ridge" not in _counts(shattered)
    merged = merge_vertices(shattered, tol=0.25)
    assert _counts(merged)["ridge"] == 1


def test_merge_recovers_valley():
    merged = merge_vertices(_shatter(valley_pair()), tol=0.25)
    assert _counts(merged)["valley"] == 1


def test_t_junction_inserts_vertex_on_edge():
    # Facet B has a long edge (0,0,0)->(10,0,0); facet A has a vertex at its
    # midpoint (5,0,0). Resolution must insert (5,0,0) into B's ring.
    b = make_facet("B", [(0, 0, 0), (10, 0, 0), (10, 5, 2), (0, 5, 2)])
    a = make_facet("A", [(5, 0, 0), (8, -3, 0), (2, -3, 0)])
    out = {f.id: f for f in resolve_t_junctions([a, b], tol=0.05)}
    bverts = out["B"].verts
    assert any(abs(v[0] - 5) < 1e-6 and abs(v[1]) < 1e-6 for v in bverts)
    assert len(bverts) == 5  # original 4 + inserted midpoint


def test_collinear_drops_redundant_but_keeps_shared_corner():
    # A square with a redundant collinear midpoint on its top edge.
    square = make_facet("sq", [
        (0, 0, 0), (10, 0, 0), (10, 10, 0), (5, 10, 0), (0, 10, 0)
    ])
    cleaned = drop_collinear([square], tol=0.03)[0]
    # The collinear (5,10,0) is dropped (not shared with any other facet).
    assert len(cleaned.verts) == 4


def test_collinear_preserves_shared_vertex():
    # (5,10,0) is collinear on sq's edge AND shared with facet 'nb' -> keep it.
    square = make_facet("sq", [
        (0, 0, 0), (10, 0, 0), (10, 10, 0), (5, 10, 0), (0, 10, 0)
    ])
    nb = make_facet("nb", [(5, 10, 0), (8, 14, 0), (2, 14, 0)])
    cleaned = {f.id: f for f in drop_collinear([square, nb], tol=0.03)}
    assert any(abs(v[0] - 5) < 1e-6 and abs(v[1] - 10) < 1e-6
               for v in cleaned["sq"].verts)


def test_weld_is_idempotent_on_clean_model():
    golden = cross_gable()
    once = weld(golden)
    assert _counts(once) == _counts(golden)

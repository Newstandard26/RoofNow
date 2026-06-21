"""
Tests for snapping.py — the shared-edge fix that makes boundary recovery work.
Mirrors the uploaded suite (adapted to the repo's module paths) plus the
cross-gable acceptance test.
"""
import math
import random

from roofwall.measurement.edges import (
    classify_edges,
    cross_gable,
    hip_roof,
    line_lengths,
    make_facet,
    summarize,
)
from roofwall.measurement.snapping import (
    from_roof_edges,
    snap_model,
    to_roof_edges,
    weld,
)

TOL = 0.5


def _summary(plain):
    return summarize(classify_edges(to_roof_edges(plain)))


def _offset_gable():
    """Two gable facets whose ridge vertices are offset by 0.1 ft — i.e. independently
    traced, so they DON'T share an edge until snapped (0.1 > edges SNAP of 0.05)."""
    front = {"id": "front", "verts": [(0, 0, 0), (40, 0, 0), (40, 12, 6), (0, 12, 6)]}
    back = {"id": "back", "verts": [(40, 24, 0), (0, 24, 0), (0.1, 12, 6), (40.1, 12, 6)]}
    return [front, back]


def test_before_snapping_ridge_is_missing():
    # offset vertices => the top edges are seen as two separate boundary edges, no ridge
    s = _summary(_offset_gable())
    assert "ridge" not in s or int(s["ridge"]["count"]) == 0


def test_snapping_recovers_the_ridge():
    s = _summary(snap_model(_offset_gable()))
    assert int(s["ridge"]["count"]) == 1
    assert abs(s["ridge"]["length"] - 40.0) < TOL
    assert int(s["eave"]["count"]) == 2
    assert abs(s["eave"]["length"] - 80.0) < TOL
    assert int(s["rake"]["count"]) == 4


def test_t_junction_vertex_is_inserted():
    # A's top edge spans 0..20; B only touches the 0..10 half, with a corner at the
    # midpoint (10,10,5) that lies ON A's edge. Resolution must insert it into A.
    A = {"id": "A", "verts": [(0, 0, 5), (20, 0, 5), (20, 10, 5), (0, 10, 5)]}
    B = {"id": "B", "verts": [(0, 10, 5), (10, 10, 5), (10, 20, 5), (0, 20, 5)]}
    out = snap_model([A, B])
    a = next(f for f in out if f["id"] == "A")
    assert any(math.dist(v, (10, 10, 5)) < 0.2 for v in a["verts"]), \
        "T-junction vertex was not inserted into facet A"


def test_idempotent_on_clean_hip_roof():
    # a roof that already shares edges should survive snapping unchanged in topology
    plain = from_roof_edges(hip_roof(40, 24, 6))
    s = _summary(snap_model(plain))
    assert int(s["ridge"]["count"]) == 1
    assert int(s["hip"]["count"]) == 4
    assert int(s["eave"]["count"]) == 4
    assert abs(s["ridge"]["length"] - 16.0) < TOL
    assert abs(s["hip"]["length"] - 72.0) < TOL


# -------------------- cross-gable acceptance (via weld) --------------------


def _shatter(facets, jitter=0.08, seed=3):
    """Re-trace each EdgeFacet independently: jitter every vertex < snap tol."""
    rng = random.Random(seed)
    return [
        make_facet(
            f.id,
            [(x + rng.uniform(-jitter, jitter),
              y + rng.uniform(-jitter, jitter),
              z + rng.uniform(-jitter, jitter)) for x, y, z in f.verts],
            source=f.source,
        )
        for f in facets
    ]


def _counts(edge_facets):
    return {k: v.count for k, v in line_lengths(edge_facets).items()}


def test_cross_gable_shared_edges_vanish_without_snapping():
    c = _counts(_shatter(cross_gable()))
    assert "ridge" not in c and "valley" not in c
    assert c["eave"] > 5  # boundary edges exploded


def test_cross_gable_weld_recovers_ridges_and_valleys():
    golden = cross_gable()
    gold = _counts(golden)
    got = _counts(weld(_shatter(golden)))
    assert gold == {"eave": 5, "rake": 6, "ridge": 3, "valley": 2}
    assert got == gold  # welding the independent tracing reproduces it exactly

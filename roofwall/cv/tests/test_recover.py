"""
Synthetic round-trip test for recover.py — the acceptance gate from the spec.

Rasterize a roof whose true measurements we know into a DSM, recover facet polygons
from that DSM, run them through snapping + edges, and assert we get the roof back.
No live API needed. This proves the DSM -> polygons -> line-lengths chain works.
"""
import pytest

# recover/synth need the geospatial stack; skip cleanly if it's absent.
pytest.importorskip("skimage")
pytest.importorskip("shapely")

from roofwall.cv.recover import recover  # noqa: E402
from roofwall.cv.synth import rasterize  # noqa: E402
from roofwall.measurement.edges import (  # noqa: E402
    classify_edges,
    gable_roof,
    hip_roof,
    summarize,
)
from roofwall.measurement.snapping import to_roof_edges  # noqa: E402


def _recover_summary(facets, res=0.5):
    dsm, mask, tf, priors = rasterize(facets, res=res)
    rec = recover(dsm, mask, tf, priors)
    return summarize(classify_edges(to_roof_edges(rec))), rec


def _pct(a, b):
    return abs(a - b) / b


def test_gable_roundtrip():
    # truth: ridge 40, eaves 80, 4 rakes (~53.7), no hips/valleys
    s, rec = _recover_summary(gable_roof(40, 24, 6))
    assert len(rec) == 2
    assert int(s["ridge"]["count"]) == 1
    assert int(s["eave"]["count"]) == 2
    assert "hip" not in s and "valley" not in s
    assert _pct(s["ridge"]["length"], 40.0) < 0.10
    assert _pct(s["eave"]["length"], 80.0) < 0.10
    assert _pct(s["rake"]["length"], 53.7) < 0.10


def test_hip_roundtrip_topology_and_lengths():
    # truth: ridge 16, 4 hips (~72), 4 eaves (128), no valleys/rakes
    s, rec = _recover_summary(hip_roof(40, 24, 6))
    assert len(rec) == 4
    assert int(s["ridge"]["count"]) == 1
    assert int(s["hip"]["count"]) == 4
    assert int(s["eave"]["count"]) == 4
    assert "valley" not in s
    assert _pct(s["ridge"]["length"], 16.0) < 0.15
    assert _pct(s["hip"]["length"], 72.0) < 0.15
    assert _pct(s["eave"]["length"], 128.0) < 0.10


def test_recovers_facet_count_for_bigger_hip():
    s, rec = _recover_summary(hip_roof(60, 30, 8))
    assert len(rec) == 4
    assert int(s["ridge"]["count"]) == 1
    assert int(s["hip"]["count"]) == 4
    assert int(s["eave"]["count"]) == 4


def test_dsm_to_building_model_bridge():
    # recover -> BuildingModel contract -> snapped Length Diagram.
    from roofwall.cv.solar_dsm import build_model_from_dsm
    from roofwall.model import Origin

    dsm, mask, tf, priors = rasterize(hip_roof(40, 24, 6), res=0.5)
    model = build_model_from_dsm(dsm, mask, tf, priors, Origin(42.0, -89.0))
    assert model.source == "solar-dsm"
    ll = model.line_lengths()
    assert ll["ridge"]["count"] == 1
    assert ll["hip"]["count"] == 4
    assert ll["eave"]["count"] == 4


def test_assign_pixels_matches_reference_and_bounds_memory():
    # The incremental assignment must match the old argmin-over-stack result
    # exactly (first plane wins ties) without allocating the (planes,H,W) stack.
    import numpy as np

    from roofwall.cv.recover import RasterTransform, assign_pixels

    rng = np.random.default_rng(0)
    nrows, ncols = 40, 50
    tf = RasterTransform(x0=0.0, y0=0.0, res=0.5, nrows=nrows)
    Xg, Yg = tf.grids(ncols)
    planes = [(0.1, -0.2, 1.0), (-0.3, 0.05, 2.0), (0.0, 0.0, 1.5),
              (0.2, 0.2, 0.5), (-0.1, -0.1, 3.0)]
    dsm = (0.2 * Xg - 0.1 * Yg + 1.0) + rng.normal(0, 0.05, (nrows, ncols))
    mask = np.ones((nrows, ncols), dtype="uint8")
    mask[:5, :5] = 0

    got = assign_pixels(dsm, mask, planes, tf, max_residual=2.0)

    resid = np.stack([np.abs(a * Xg + b * Yg + c - dsm) for (a, b, c) in planes])
    ref = np.argmin(resid, axis=0)
    ref = np.where((mask > 0) & (resid.min(axis=0) <= 2.0), ref, -1)
    assert np.array_equal(got, ref)

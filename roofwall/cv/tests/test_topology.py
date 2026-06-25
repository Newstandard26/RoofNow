"""Roof-topology recovery acceptance tests (DSM/mask/prior -> clean facets).

Exercises the production light path end-to-end (build_model_light) on synthetic
roofs whose true topology we know, asserting the acceptance criteria from the
recovery spec: gable/hip/cross-gable topology, no eave/rake explosion, detached
neighbouring structures isolated, and the debug + QA payload populated. No live
API calls — DSM/mask/segments are rasterised from known facets.
"""
import pytest

pytest.importorskip("tifffile")
pytest.importorskip("contourpy")

import numpy as np  # noqa: E402

from roofwall.cv.light import build_model_light, _target_component  # noqa: E402
from roofwall.measurement.edges import (  # noqa: E402
    cross_gable, gable_roof, hip_roof, make_facet,
)

import sys  # noqa: E402
import os  # noqa: E402
sys.path.insert(0, os.path.dirname(__file__))
from test_light import _synth, LAT0, LON0  # noqa: E402


def _model(facets, *, noise_ft=0.0, extra_segs=None):
    dsm_b, mask_b, segs = _synth(facets, noise_ft=noise_ft)
    if extra_segs:
        segs = segs + extra_segs
    payload = {"solarPotential": {"roofSegmentStats": segs}}

    class FakeClient:
        def building_insights(self, lat, lng):
            return payload

        def data_layers(self, lat, lng, radius_m=50.0):
            return {"dsmUrl": "http://x/dsm", "maskUrl": "http://x/mask"}

    def fetch(url, key):
        return dsm_b if url.endswith("dsm") else mask_b

    return build_model_light(LAT0, LON0, "k", client=FakeClient(), fetch=fetch)


def _counts(model):
    ll = model.line_lengths()
    return {k: ll.get(k, {"count": 0})["count"]
            for k in ("ridge", "hip", "valley", "rake", "eave")}


# ---------------------------------------------------------------- gable
def test_gable_topology():
    m = _model(gable_roof(40, 24, 6))
    c = _counts(m)
    assert c["ridge"] == 1            # one ridge along the peak
    assert c["hip"] == 0 and c["valley"] == 0
    assert c["eave"] == 2            # two long eaves
    assert c["rake"] == 4            # two sloped rakes per gable end
    assert len(m.facets) == 2        # two real facets (not collapsed to one)


# ---------------------------------------------------------------- hip
def test_hip_topology_no_false_valleys():
    m = _model(hip_roof(40, 24, 6))
    c = _counts(m)
    assert c["ridge"] == 1
    assert c["hip"] == 4
    assert c["valley"] == 0           # a hip roof has no valleys
    assert c["eave"] == 4
    assert len(m.facets) == 4


# ---------------------------------------------------------------- cross gable
def test_cross_gable_detects_valleys_no_explosion():
    m = _model(cross_gable())
    c = _counts(m)
    assert c["valley"] >= 2           # the two reentrant valleys are found
    assert c["ridge"] >= 2
    # no eave/rake explosion from unsnapped shared edges
    assert c["eave"] + c["rake"] <= 5 * max(len(m.facets), 1)
    assert 4 <= len(m.facets) <= 6


# ---------------------------------------------------------------- multi-plane
def test_multiplane_roof_no_edge_explosion():
    # A larger cut-up roof (cross gable scaled up + noise) must still weld into a
    # coherent skeleton rather than spraying short unshared rakes.
    m = _model(cross_gable(), noise_ft=0.25)
    c = _counts(m)
    assert len(m.facets) >= 4
    assert c["valley"] >= 1
    assert c["eave"] + c["rake"] <= 5 * len(m.facets)
    d = m.debug
    assert d["qa"] in ("ok", "review")           # not low_confidence on clean-ish DSM
    assert "possible_edge_fragmentation" not in d["warnings"]


# ---------------------------------------------------------------- detached garage
def _translate(facets, dx, dy):
    out = []
    for f in facets:
        out.append(make_facet(f.id + "_g",
                              [(x + dx, y + dy, z) for (x, y, z) in f.verts]))
    return out


def test_detached_garage_is_isolated():
    # Main hip + a detached garage 4 ft away (separate mask blob). The tile is
    # centred on the combined bbox, which lands on the main building, so recovery
    # must keep only the main roof and flag that the tile held >1 structure.
    main = hip_roof(40, 24, 6)
    garage = _translate(gable_roof(12, 12, 5), dx=44.0, dy=6.0)
    m = _model(main + garage)
    # only the main hip's 4 facets survive — garage dropped
    assert len(m.facets) == 4
    c = _counts(m)
    assert c["ridge"] == 1 and c["hip"] == 4
    d = m.debug
    assert d["target_component_sqft"] < d["mask_sqft"]    # garage excluded from target
    assert "multiple_structures_in_tile" in d["warnings"]


def test_target_component_unit():
    # two separate blobs + an interior hole; seed on blob A
    region = np.zeros((40, 60), dtype=bool)
    region[5:25, 5:25] = True            # blob A (building)
    region[10:15, 10:13] = False         # interior hole (chimney)
    region[5:25, 40:55] = True           # blob B (detached garage)
    comp = _target_component(region, (15, 15), res=0.5)
    assert comp[5:25, 5:25].all()        # blob A fully kept
    assert comp[12, 11]                  # interior hole filled
    assert not comp[:, 40:55].any()      # detached blob B dropped


# ---------------------------------------------------------------- debug payload
def test_debug_payload_complete():
    m = _model(hip_roof(40, 24, 6))
    d = m.debug
    for key in ("qa", "warnings", "grid", "res_ft", "mask_sqft",
                "target_component_sqft", "n_solar_segments", "n_merged_priors",
                "n_planes_kept", "n_facets", "facet_areas_sqft", "roof_area_sqft",
                "coverage_pct", "unassigned_pct", "mean_residual_ft",
                "p95_residual_ft", "edge_counts", "used_fallback", "anchor"):
        assert key in d, f"missing debug field: {key}"
    assert d["grid"] == [m.debug["grid"][0], m.debug["grid"][1]]
    assert d["n_solar_segments"] == 4
    assert d["edge_counts"]["hip"] == 4
    assert isinstance(d["warnings"], list)
    assert d["qa"] == "ok"


def test_low_confidence_flags_qa():
    # A badly corrupted DSM (heavy noise) must NOT silently fabricate clean lines:
    # recovery should raise warnings and downgrade qa away from "ok".
    m = _model(hip_roof(40, 24, 6), noise_ft=3.5)
    d = m.debug
    assert d["qa"] in ("review", "low_confidence")
    assert d["warnings"]                 # at least one warning surfaced


# ---------------------------------------------------------------- PEARL labeler
def test_pearl_used_when_maxflow_installed():
    # With PyMaxflow available the diagram partition must use the graph-cut
    # (PEARL), not the greedy fallback.
    pytest.importorskip("maxflow")
    m = _model(hip_roof(40, 24, 6))
    assert m.debug["diagram_labeler"] == "pearl"


def test_pearl_falls_back_gracefully_without_maxflow(monkeypatch):
    # Simulate a deploy where PyMaxflow failed to install: _pearl_labels imports
    # maxflow.fastmin lazily, so blocking the import in sys.modules forces the
    # greedy fallback. Recovery must still succeed and report the fallback.
    monkeypatch.setitem(sys.modules, "maxflow", None)
    monkeypatch.setitem(sys.modules, "maxflow.fastmin", None)
    m = _model(hip_roof(40, 24, 6))
    assert m.debug["diagram_labeler"] == "greedy_fallback"
    assert len(m.facets) >= 1            # greedy labels still yield a usable roof


# ---------------------------------------------------------------- polygon cleanup
def _polys(model):
    from shapely.geometry import Polygon
    out = []
    for f in model.to_edge_facets():
        xy = [(v[0], v[1]) for v in f.verts]
        if len(xy) >= 3:
            out.append(Polygon(xy))
    return out


def test_diagram_polygons_are_clean_and_non_overlapping():
    for facets in (gable_roof(40, 24, 6), hip_roof(40, 24, 6), cross_gable()):
        m = _model(facets)
        ps = _polys(m)
        assert all(p.is_valid for p in ps), "self-intersecting polygon in roof_diagram"
        ov = sum(ps[i].intersection(ps[j]).area
                 for i in range(len(ps)) for j in range(i + 1, len(ps)))
        assert ov < 2.0, f"facets overlap by {ov:.1f} sqft"
        assert m.debug["qa_required"] is False
        assert m.debug["diagram_overlap_sqft"] < 2.0


def test_clean_facet_polygons_unit():
    from roofwall.cv.light import _clean_facet_polygons
    from roofwall.cv.recover import RasterTransform
    from shapely.geometry import Polygon

    t = RasterTransform(x0=0, y0=0, res=0.5, nrows=100)

    def F(fid, xy):
        return {"id": fid, "verts": [(x, y, 0.0) for x, y in xy]}

    facets = [
        F("A", [(0, 0), (20, 0), (20, 20), (0, 20)]),          # 400 sqft
        F("B", [(15, 0), (35, 0), (35, 20), (15, 20)]),        # overlaps A by 100
        F("star", [(40, 0), (60, 20), (40, 20), (60, 0)]),     # bowtie self-intersection
        F("sliver", [(0, 30), (40, 30), (40, 31), (0, 31)]),   # 1 ft thick
        F("tiny", [(50, 30), (53, 30), (53, 33), (50, 33)]),   # 9 sqft < min
    ]
    foot = Polygon([(0, 0), (60, 0), (60, 40), (0, 40)])
    clean, dbg = _clean_facet_polygons(facets, foot, t, min_facet_area_sqft=25.0)

    out = [Polygon([(v[0], v[1]) for v in f["verts"]]) for f in clean]
    assert all(p.is_valid for p in out)               # no self-intersection in output
    ov = sum(out[i].intersection(out[j]).area
             for i in range(len(out)) for j in range(i + 1, len(out)))
    assert ov < 1e-6                                  # overlaps removed
    reasons = {r["reason"] for r in dbg["rejected_polygons"]}
    assert "sliver" in reasons and "below_min_area" in reasons
    assert dbg["polygons_before_cleanup"] == 5
    assert dbg["polygons_after_cleanup"] == len(clean)


def test_clean_facet_polygons_splits_disconnected_label():
    # a facet clipped into two disconnected pieces (a neighbour cutting through the
    # middle) must split into two separate facets, not one self-touching polygon.
    from roofwall.cv.light import _clean_facet_polygons
    from roofwall.cv.recover import RasterTransform
    from shapely.geometry import Polygon

    t = RasterTransform(x0=0, y0=0, res=0.5, nrows=100)
    facets = [
        # the bigger bar is placed first and keeps its area...
        {"id": "BIG", "verts": [(0, 0, 0), (30, 0, 0), (30, 10, 0), (0, 10, 0)]},
        # ...the smaller crossing bar gets cut into two disconnected halves by it
        {"id": "SPLIT", "verts": [(12, -6, 0), (18, -6, 0), (18, 16, 0), (12, 16, 0)]},
    ]
    foot = Polygon([(-5, -10), (40, -10), (40, 20), (-5, 20)])
    clean, dbg = _clean_facet_polygons(facets, foot, t, min_facet_area_sqft=25.0)
    split_pieces = [f for f in clean if f["id"].startswith("SPLIT")]
    assert len(split_pieces) == 2                      # disconnected halves split out


def test_overlap_flagged_sets_qa_required(monkeypatch):
    # If the topology guard ever leaves residual overlap, recovery must NOT present
    # the diagram as final: qa_required=true + the specific warning.
    import roofwall.cv.light as L
    real = L._clean_facet_polygons

    def leak_overlap(facets, footprint, transform, **kw):
        clean, dbg = real(facets, footprint, transform, **kw)
        dbg["qa_required"] = True
        dbg["overlap_sqft"] = 9.9
        return clean, dbg

    monkeypatch.setattr(L, "_clean_facet_polygons", leak_overlap)
    m = _model(hip_roof(40, 24, 6))
    assert m.debug["qa_required"] is True
    assert "diagram_polygons_overlap" in m.debug["warnings"]
    assert m.debug["qa"] in ("review", "low_confidence")


def test_debug_overlay_fields_present():
    m = _model(hip_roof(40, 24, 6))
    d = m.debug
    for key in ("diagram_labeler", "polygons_before_cleanup", "polygons_after_cleanup",
                "rejected_polygons", "diagram_overlap_sqft", "qa_required", "raw_labels"):
        assert key in d, f"missing debug overlay field: {key}"
    rl = d["raw_labels"]
    assert set(rl) == {"origin", "shape", "labels"}
    assert len(rl["labels"]) == rl["shape"][0]        # one row per shape height


def test_pearl_labels_returns_labeler_tag():
    # Unit-level: _pearl_labels reports which labeler ran for both paths.
    import numpy as np
    from roofwall.cv.light import _pearl_labels
    from roofwall.cv.recover import RasterTransform, plane_from_solar_segment

    t = RasterTransform(x0=0.0, y0=0.0, res=1.0, nrows=20)
    Xg, Yg = t.grids(20)
    dsm = np.zeros((20, 20))
    region = np.zeros((20, 20), dtype=bool)
    region[5:15, 5:15] = True
    planes = [plane_from_solar_segment(20, 180, (10, 10, 0))]

    _, _, tag = _pearl_labels(dsm, region, t, Xg, Yg, planes, iters=1)
    assert tag in ("pearl", "greedy_fallback")
    if "maxflow" in sys.modules and sys.modules["maxflow"] is not None:
        assert tag == "pearl"

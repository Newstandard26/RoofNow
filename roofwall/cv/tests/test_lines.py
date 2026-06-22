"""measure_lines: roof line lengths from planes + a labelled raster."""
import math

import pytest

pytest.importorskip("contourpy")

import numpy as np  # noqa: E402

from roofwall.cv.lines import measure_lines  # noqa: E402
from roofwall.cv.recover import RasterTransform, abc_from_normal  # noqa: E402
from roofwall.cv.recover import plane_z  # noqa: E402
from roofwall.cv.synth import _point_in_poly2d  # noqa: E402
from roofwall.measurement.edges import gable_roof, hip_roof  # noqa: E402

RES = 0.5


def _rasterize(facets):
    """Clean labelled raster + true planes for a roof, in a local-feet frame."""
    planes = [abc_from_normal(f.normal, f.verts[0]) for f in facets]
    xs = [v[0] for f in facets for v in f.verts]
    ys = [v[1] for f in facets for v in f.verts]
    pad = 3 * RES
    x0, y0 = min(xs) - pad, min(ys) - pad
    ncols = int(math.ceil((max(xs) + pad - x0) / RES)) + 1
    nrows = int(math.ceil((max(ys) + pad - y0) / RES)) + 1
    tf = RasterTransform(x0=x0, y0=y0, res=RES, nrows=nrows)
    labels = np.full((nrows, ncols), -1, dtype=int)
    for r in range(nrows):
        for c in range(ncols):
            x, y = tf.colrow_to_world(c, r)
            best_i, best_z = -1, -1e18
            for i, f in enumerate(facets):
                if _point_in_poly2d(x, y, f.verts):
                    z = plane_z(planes[i], x, y)
                    if z > best_z:
                        best_z, best_i = z, i
            labels[r, c] = best_i
    return labels, planes, tf


def test_hip_lines_match_ground_truth():
    labels, planes, tf = _rasterize(hip_roof(40, 24, 6))
    ll = measure_lines(labels, planes, tf)
    assert ll["ridge"]["count"] == 1
    assert ll["hip"]["count"] == 4
    assert ll["eave"]["count"] == 4
    assert "rake" not in ll and "valley" not in ll          # a hip has neither
    assert ll["ridge"]["length_ft"] == pytest.approx(16.0, abs=3.0)
    assert ll["hip"]["length_ft"] == pytest.approx(72.0, rel=0.15)
    assert ll["eave"]["length_ft"] == pytest.approx(128.0, rel=0.1)


def test_gable_lines_have_rakes_not_hips():
    labels, planes, tf = _rasterize(gable_roof(40, 24, 6))
    ll = measure_lines(labels, planes, tf)
    assert ll["ridge"]["count"] == 1
    assert ll["eave"]["count"] == 2
    assert "hip" not in ll                                   # a gable has no hips
    assert ll["rake"]["count"] == 4
    assert ll["eave"]["length_ft"] == pytest.approx(80.0, rel=0.1)

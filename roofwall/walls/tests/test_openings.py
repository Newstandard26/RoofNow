"""Façade homography + opening measurement."""

import numpy as np
import pytest

from roofwall.walls.openings import (
    apply_homography,
    compute_homography,
    facade_homography,
    measure_opening,
    total_opening_area,
)

# A façade photographed obliquely: the real façade is 30 ft x 12 ft, but in
# the image its corners form a trapezoid (perspective).
REAL_W, REAL_H = 30.0, 12.0
FACADE_PX = [(100, 80), (520, 60), (560, 400), (60, 430)]  # TL, TR, BR, BL


def test_homography_maps_facade_corners_to_rectangle():
    h = facade_homography(FACADE_PX, REAL_W, REAL_H)
    expected = [(0, 0), (REAL_W, 0), (REAL_W, REAL_H), (0, REAL_H)]
    for px, exp in zip(FACADE_PX, expected):
        u, v = apply_homography(h, px)
        assert u == pytest.approx(exp[0], abs=1e-6)
        assert v == pytest.approx(exp[1], abs=1e-6)


def test_identity_homography():
    pts = [(0, 0), (1, 0), (1, 1), (0, 1)]
    h = compute_homography(pts, pts)
    for p in pts:
        assert apply_homography(h, p) == pytest.approx(p, abs=1e-9)


def test_measure_opening_in_rectified_facade():
    # Build a synthetic façade where pixels map linearly to feet so we can
    # place an opening at a known real size. Use an affine (square) façade.
    facade_px = [(0, 0), (300, 0), (300, 120), (0, 120)]  # 10 px / ft
    h = facade_homography(facade_px, REAL_W, REAL_H)
    # A window occupying px (30,24)-(90,84) -> 6 ft wide x 6 ft tall.
    window_px = [(30, 24), (90, 24), (90, 84), (30, 84)]
    op = measure_opening(h, window_px, kind="window")
    assert op.width_ft == pytest.approx(6.0, abs=1e-6)
    assert op.height_ft == pytest.approx(6.0, abs=1e-6)
    assert op.area_sqft == pytest.approx(36.0, abs=1e-5)


def test_total_opening_area():
    facade_px = [(0, 0), (300, 0), (300, 120), (0, 120)]
    h = facade_homography(facade_px, REAL_W, REAL_H)
    win = [(30, 24), (90, 24), (90, 84), (30, 84)]      # 6x6 = 36
    door = [(150, 30), (210, 30), (210, 120), (150, 120)]  # 6 x 9 = 54
    total = total_opening_area(h, [win, door])
    assert total == pytest.approx(36.0 + 54.0, abs=1e-4)


def test_opening_recovered_under_perspective():
    # Even with an oblique façade, a window measured through the homography
    # recovers its true size. Map real coords back through the inverse.
    h = facade_homography(FACADE_PX, REAL_W, REAL_H)
    h_inv = np.linalg.inv(h)
    # Real window: 4 ft wide, 5 ft tall, lower-left at (10, 4).
    real_corners = [(10, 4), (14, 4), (14, 9), (10, 9)]
    window_px = [apply_homography(h_inv, p) for p in real_corners]
    op = measure_opening(h, window_px)
    assert op.width_ft == pytest.approx(4.0, abs=1e-4)
    assert op.height_ft == pytest.approx(5.0, abs=1e-4)


def test_bad_homography_inputs():
    with pytest.raises(ValueError):
        compute_homography([(0, 0), (1, 0)], [(0, 0), (1, 0)])  # too few
    with pytest.raises(ValueError):
        facade_homography(FACADE_PX, -1.0, 12.0)  # bad dims

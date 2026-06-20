"""Footprint geometry helpers."""

import math

import pytest

from roofwall.measurement.geometry import (
    bearing_degrees,
    centroid,
    distance,
    polygon_area,
    polygon_perimeter,
    signed_area,
)

# A 40 x 30 rectangle.
RECT = [(0.0, 0.0), (40.0, 0.0), (40.0, 30.0), (0.0, 30.0)]


def test_polygon_area_rectangle():
    assert polygon_area(RECT) == pytest.approx(1200.0)


def test_polygon_area_closed_ring():
    closed = RECT + [RECT[0]]
    assert polygon_area(closed) == pytest.approx(1200.0)


def test_polygon_area_orientation_independent():
    assert polygon_area(list(reversed(RECT))) == pytest.approx(1200.0)


def test_polygon_area_triangle():
    tri = [(0.0, 0.0), (4.0, 0.0), (0.0, 3.0)]
    assert polygon_area(tri) == pytest.approx(6.0)


def test_polygon_perimeter_rectangle():
    assert polygon_perimeter(RECT) == pytest.approx(140.0)


def test_distance():
    assert distance((0, 0), (3, 4)) == pytest.approx(5.0)


def test_signed_area_winding():
    assert signed_area(RECT) > 0  # CCW
    assert signed_area(list(reversed(RECT))) < 0  # CW


def test_centroid_rectangle():
    cx, cy = centroid(RECT)
    assert cx == pytest.approx(20.0)
    assert cy == pytest.approx(15.0)


def test_bearing_cardinal_directions():
    origin = (0.0, 0.0)
    assert bearing_degrees(origin, (0, 1)) == pytest.approx(0.0)    # North
    assert bearing_degrees(origin, (1, 0)) == pytest.approx(90.0)   # East
    assert bearing_degrees(origin, (0, -1)) == pytest.approx(180.0) # South
    assert bearing_degrees(origin, (-1, 0)) == pytest.approx(270.0) # West


def test_degenerate_polygon_area():
    assert polygon_area([(0, 0), (1, 1)]) == 0.0

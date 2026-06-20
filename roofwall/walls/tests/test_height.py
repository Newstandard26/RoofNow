"""Wall height & per-elevation breakdown."""

import pytest

from roofwall.walls.height import (
    WallBreakdown,
    bearing_to_cardinal4,
    building_height,
    elevation_breakdown,
    wall_normal_cardinal,
)

# 40 (E-W) x 30 (N-S) rectangle, wound counter-clockwise.
#   (0,0) -> (40,0) -> (40,30) -> (0,30)
RECT = [(0.0, 0.0), (40.0, 0.0), (40.0, 30.0), (0.0, 30.0)]


def test_building_height():
    assert building_height(28.0, 10.0) == pytest.approx(18.0)
    assert building_height(10.0, 12.0) == pytest.approx(0.0)  # clamped


@pytest.mark.parametrize(
    "bearing,card",
    [(0, "N"), (44, "N"), (45, "E"), (90, "E"), (180, "S"), (270, "W"), (359, "N")],
)
def test_bearing_to_cardinal4(bearing, card):
    assert bearing_to_cardinal4(bearing) == card


def test_wall_normal_cardinal_ccw_rectangle():
    # CCW rectangle: bottom edge faces S, right faces E, top N, left W.
    assert wall_normal_cardinal((0, 0), (40, 0)) == "S"
    assert wall_normal_cardinal((40, 0), (40, 30)) == "E"
    assert wall_normal_cardinal((40, 30), (0, 30)) == "N"
    assert wall_normal_cardinal((0, 30), (0, 0)) == "W"


def test_elevation_breakdown_rectangle():
    h = 10.0
    bd = elevation_breakdown(RECT, h)
    # N & S walls are the 40-ft sides; E & W are the 30-ft sides.
    assert bd.by_direction["N"] == pytest.approx(40 * h)
    assert bd.by_direction["S"] == pytest.approx(40 * h)
    assert bd.by_direction["E"] == pytest.approx(30 * h)
    assert bd.by_direction["W"] == pytest.approx(30 * h)
    # Gross matches 2*h*(l+w).
    assert bd.gross_wall_area == pytest.approx(2 * h * (40 + 30))


def test_elevation_breakdown_with_gables():
    bd = elevation_breakdown(RECT, 10.0, gables=[(30.0, 7.5), (30.0, 7.5)])
    assert bd.gable_area == pytest.approx(2 * (30 * 7.5 / 2))
    assert bd.gross_wall_area == pytest.approx(2 * 10 * 70 + 225.0)


def test_net_siding_from_breakdown():
    bd = elevation_breakdown(RECT, 10.0)
    net = bd.net_siding_area(openings=[15.0, 21.0], waste_pct=0.10)
    assert net == pytest.approx((1400.0 - 36.0) * 1.10)


def test_closed_ring_accepted():
    closed = RECT + [RECT[0]]
    bd = elevation_breakdown(closed, 10.0)
    assert bd.gross_wall_area == pytest.approx(1400.0)


def test_bad_inputs():
    with pytest.raises(ValueError):
        elevation_breakdown([(0, 0), (1, 1)], 10.0)
    with pytest.raises(ValueError):
        elevation_breakdown(RECT, -1.0)

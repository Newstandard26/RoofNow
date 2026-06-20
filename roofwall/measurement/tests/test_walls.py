"""Wall area, gables, openings, waste & sanity-check formulas."""

import math

import pytest

from roofwall.measurement.engine import (
    WasteCategory,
    gable_triangle_area,
    ground_sample_distance,
    gross_wall_area,
    height_from_shadow,
    net_siding_area,
    suggest_waste_from_facets,
    suggest_waste_pct,
    wall_area_from_perimeter,
)


def test_gross_wall_area_rectangle():
    # 40 x 30 footprint, 10 ft walls -> 2*10*(40+30) = 1400.
    assert gross_wall_area(40.0, 30.0, 10.0) == pytest.approx(1400.0)


def test_wall_area_from_perimeter_matches_rectangle():
    perimeter = 2 * (40.0 + 30.0)
    assert wall_area_from_perimeter(perimeter, 10.0) == pytest.approx(
        gross_wall_area(40.0, 30.0, 10.0)
    )


def test_gable_triangle_area():
    assert gable_triangle_area(30.0, 7.5) == pytest.approx(112.5)


def test_net_siding_subtracts_openings():
    gross = 1400.0
    openings = [15.0, 15.0, 21.0]  # two windows + a door
    assert net_siding_area(gross, openings) == pytest.approx(1400.0 - 51.0)


def test_net_siding_with_waste():
    gross = 1000.0
    net = net_siding_area(gross, [100.0], waste_pct=0.10)
    assert net == pytest.approx(900.0 * 1.10)


def test_net_siding_never_negative():
    assert net_siding_area(100.0, [200.0]) == pytest.approx(0.0)


def test_net_siding_no_openings():
    assert net_siding_area(1400.0) == pytest.approx(1400.0)


def test_suggest_waste_categories():
    assert suggest_waste_pct(WasteCategory.SIMPLE_GABLE) == pytest.approx(0.05)
    assert suggest_waste_pct(WasteCategory.TYPICAL) == pytest.approx(0.12)
    assert suggest_waste_pct(WasteCategory.COMPLEX) == pytest.approx(0.18)
    assert suggest_waste_pct(WasteCategory.TILE) == pytest.approx(0.18)


def test_suggest_waste_from_facets():
    assert suggest_waste_from_facets(2) == pytest.approx(0.05)
    assert suggest_waste_from_facets(4) == pytest.approx(0.12)
    assert suggest_waste_from_facets(10) == pytest.approx(0.18)
    assert suggest_waste_from_facets(4, tile=True) == pytest.approx(0.18)


def test_height_from_shadow():
    # 45-degree sun -> height equals shadow length.
    assert height_from_shadow(20.0, 45.0) == pytest.approx(20.0)
    # 30-degree sun -> height = shadow * tan(30).
    assert height_from_shadow(20.0, 30.0) == pytest.approx(20.0 * math.tan(math.radians(30)))


def test_height_from_shadow_invalid():
    with pytest.raises(ValueError):
        height_from_shadow(20.0, 0.0)
    with pytest.raises(ValueError):
        height_from_shadow(20.0, 90.0)


def test_ground_sample_distance():
    # altitude 120 m, pixel pitch 4 micron (in m), focal 24 mm (in m).
    gsd = ground_sample_distance(120.0, 4e-6, 0.024)
    assert gsd == pytest.approx(120.0 * 4e-6 / 0.024)
    assert gsd == pytest.approx(0.02)  # 2 cm/px


def test_gsd_invalid_focal():
    with pytest.raises(ValueError):
        ground_sample_distance(120.0, 4e-6, 0.0)


def test_negative_wall_inputs_raise():
    with pytest.raises(ValueError):
        gross_wall_area(-1.0, 30.0, 10.0)
    with pytest.raises(ValueError):
        gable_triangle_area(-1.0, 5.0)

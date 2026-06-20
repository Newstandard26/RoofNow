"""Roof area, squares, lengths, ordering & unit conversions."""

import math

import pytest

from roofwall.measurement.engine import (
    ROOFING_SQUARE_SQFT,
    SQM_TO_SQFT,
    Pitch,
    measure_facet,
    order_area,
    order_squares,
    rake_length,
    sloped_area,
    sqm_to_sqft,
    squares,
    summarize_roof,
)


def test_roofing_square_constant():
    assert ROOFING_SQUARE_SQFT == 100.0


def test_squares_from_area():
    assert squares(2000.0) == pytest.approx(20.0)
    assert squares(2345.0) == pytest.approx(23.45)


def test_sloped_area_uses_multiplier():
    p = Pitch.from_x12(6)  # multiplier ~1.118
    assert sloped_area(1000.0, p) == pytest.approx(1000.0 * p.multiplier)
    assert sloped_area(1000.0, p) == pytest.approx(1118.0, abs=0.5)


def test_flat_roof_sloped_equals_footprint():
    assert sloped_area(1500.0, Pitch(rise=0)) == pytest.approx(1500.0)


def test_rake_length():
    p = Pitch.from_x12(8)  # multiplier ~1.202
    assert rake_length(20.0, p) == pytest.approx(20.0 * p.multiplier)
    assert rake_length(20.0, p) == pytest.approx(24.04, abs=0.05)


def test_order_area_with_waste():
    assert order_area(2000.0, 0.10) == pytest.approx(2200.0)
    assert order_area(2000.0, 0.0) == pytest.approx(2000.0)


def test_order_squares_rounds_up():
    # 2000 sqft sloped, 10% waste -> 22 squares exactly.
    assert order_squares(2000.0, 0.10) == 22
    # 2010 sqft, 10% waste -> 22.11 -> 23.
    assert order_squares(2010.0, 0.10) == 23
    # Whole number stays whole.
    assert order_squares(2000.0, 0.0) == 20


def test_sqm_to_sqft_conversion():
    assert sqm_to_sqft(1.0) == pytest.approx(SQM_TO_SQFT)
    assert sqm_to_sqft(100.0) == pytest.approx(1076.39, abs=0.01)


def test_measure_facet_consistency():
    f = measure_facet(
        footprint_area_sqft=1000.0,
        pitch=Pitch.from_x12(6),
        azimuth_deg=180.0,
    )
    assert f.sloped_area_sqft == pytest.approx(1000.0 * f.pitch.multiplier)
    assert f.squares == pytest.approx(f.sloped_area_sqft / 100.0)
    assert f.azimuth_deg == 180.0


def test_azimuth_normalized():
    f = measure_facet(
        footprint_area_sqft=500.0,
        pitch=Pitch.from_x12(4),
        azimuth_deg=370.0,
    )
    assert f.azimuth_deg == pytest.approx(10.0)


def test_summarize_roof_totals():
    facets = [
        measure_facet(footprint_area_sqft=1000.0, pitch=Pitch.from_x12(6), azimuth_deg=180),
        measure_facet(footprint_area_sqft=1000.0, pitch=Pitch.from_x12(6), azimuth_deg=0),
    ]
    report = summarize_roof(facets, waste_pct=0.10)
    expected_sloped = 2 * 1000.0 * Pitch.from_x12(6).multiplier
    assert report.total_sloped_sqft == pytest.approx(expected_sloped)
    assert report.total_squares == pytest.approx(expected_sloped / 100.0)
    assert report.order_squares == math.ceil(expected_sloped * 1.10 / 100.0)
    assert report.predominant_pitch.x12 == pytest.approx(6.0)


def test_summarize_roof_auto_waste_simple_gable():
    # 2 facets -> simple gable -> 5% waste.
    facets = [
        measure_facet(footprint_area_sqft=800.0, pitch=Pitch.from_x12(5), azimuth_deg=180),
        measure_facet(footprint_area_sqft=800.0, pitch=Pitch.from_x12(5), azimuth_deg=0),
    ]
    report = summarize_roof(facets)
    assert report.waste_pct == pytest.approx(0.05)


def test_negative_inputs_raise():
    with pytest.raises(ValueError):
        sloped_area(-1.0, Pitch.from_x12(6))
    with pytest.raises(ValueError):
        rake_length(-1.0, Pitch.from_x12(6))
    with pytest.raises(ValueError):
        order_area(1000.0, -0.1)

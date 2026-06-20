"""Validate Pitch + multiplier/factor formulas against the spec tables."""

import math

import pytest

from roofwall.measurement.engine import (
    Pitch,
    hip_valley_factor,
    pitch_multiplier,
)

# Reference pitch multipliers from the spec (rise/12 -> sqrt(1+(rise/12)^2)).
PITCH_MULTIPLIER_TABLE = {
    3: 1.031,
    4: 1.054,
    5: 1.083,
    6: 1.118,
    7: 1.158,
    8: 1.202,
    9: 1.250,
    10: 1.302,
    12: 1.414,
}

# Reference hip/valley factors from the spec.
HIP_VALLEY_TABLE = {
    4: 1.453,
    6: 1.500,
    8: 1.564,
    12: 1.732,
}


# Spec tables are rounded to 3 decimals, so compare at that precision.
_TABLE_TOL = 1e-3


@pytest.mark.parametrize("rise,expected", PITCH_MULTIPLIER_TABLE.items())
def test_pitch_multiplier_table(rise, expected):
    assert pitch_multiplier(rise, 12) == pytest.approx(expected, abs=_TABLE_TOL)
    assert Pitch.from_x12(rise).multiplier == pytest.approx(expected, abs=_TABLE_TOL)


@pytest.mark.parametrize("rise,expected", HIP_VALLEY_TABLE.items())
def test_hip_valley_factor_table(rise, expected):
    assert hip_valley_factor(rise, 12) == pytest.approx(expected, abs=_TABLE_TOL)
    assert Pitch.from_x12(rise).hip_valley_factor == pytest.approx(
        expected, abs=_TABLE_TOL
    )


def test_pitch_multiplier_formula_identity():
    # multiplier = sqrt(1 + ratio^2)
    for rise in range(0, 25):
        p = Pitch(rise=rise, run=12)
        assert p.multiplier == pytest.approx(math.sqrt(1 + (rise / 12) ** 2))


def test_hip_valley_formula_identity():
    for rise in range(0, 25):
        p = Pitch(rise=rise, run=12)
        assert p.hip_valley_factor == pytest.approx(math.sqrt((rise / 12) ** 2 + 2))


def test_flat_roof_multiplier_is_one():
    assert Pitch(rise=0, run=12).multiplier == pytest.approx(1.0)
    assert Pitch(rise=0).percent_slope == pytest.approx(0.0)
    assert Pitch(rise=0).degrees == pytest.approx(0.0)


def test_45_degree_pitch_is_12_12():
    p = Pitch.from_degrees(45.0)
    assert p.x12 == pytest.approx(12.0)
    assert p.multiplier == pytest.approx(math.sqrt(2))
    assert p.degrees == pytest.approx(45.0)


def test_degrees_roundtrip():
    for deg in (10.0, 18.43, 26.57, 33.69, 45.0, 60.0):
        p = Pitch.from_degrees(deg)
        assert p.degrees == pytest.approx(deg, abs=1e-9)


def test_known_angle_to_x12():
    # 6/12 pitch -> atan(0.5) = 26.565 degrees.
    p = Pitch.from_x12(6)
    assert p.degrees == pytest.approx(26.565, abs=1e-3)
    # Round-trip via from_degrees.
    assert Pitch.from_degrees(p.degrees).x12 == pytest.approx(6.0)


def test_percent_slope():
    assert Pitch(rise=6, run=12).percent_slope == pytest.approx(50.0)
    assert Pitch(rise=12, run=12).percent_slope == pytest.approx(100.0)


def test_label():
    assert Pitch.from_x12(6).label() == "6/12"
    assert Pitch.from_x12(12).label() == "12/12"
    assert Pitch.from_degrees(45).label() == "12/12"


def test_invalid_pitch_inputs():
    with pytest.raises(ValueError):
        Pitch(rise=-1, run=12)
    with pytest.raises(ValueError):
        Pitch(rise=6, run=0)
    with pytest.raises(ValueError):
        Pitch.from_degrees(90)
    with pytest.raises(ValueError):
        Pitch.from_degrees(-5)

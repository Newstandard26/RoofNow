"""Roof edge classification — mirrors the validated roofEdges.test.ts suite."""

import math

import pytest

from roofwall.measurement.edges import (
    gable_roof,
    hip_roof,
    line_lengths,
    line_lengths_dict,
    pitch_x12,
    valley_pair,
)

TOL = 0.1  # ft


def test_hip_roof_topology_and_lengths():
    s = line_lengths(hip_roof(40, 24, 6))
    assert s["ridge"].count == 1
    assert s["hip"].count == 4
    assert s["eave"].count == 4
    assert "valley" not in s
    assert "rake" not in s
    assert abs(s["ridge"].length - 16) < TOL
    assert abs(s["hip"].length - 72) < TOL    # 4 * 18
    assert abs(s["eave"].length - 128) < TOL  # 2 * (40 + 24)


def test_gable_roof_produces_rakes_not_hips():
    s = line_lengths(gable_roof(40, 24, 6))
    assert s["ridge"].count == 1
    assert s["eave"].count == 2
    assert s["rake"].count == 4
    assert "hip" not in s
    assert "valley" not in s
    assert abs(s["ridge"].length - 40) < TOL
    assert abs(s["eave"].length - 80) < TOL
    assert abs(s["rake"].length - 4 * math.sqrt(12**2 + 6**2)) < TOL


def test_valley_discriminated_from_hip():
    s = line_lengths(valley_pair())
    assert "valley" in s
    assert "hip" not in s
    assert s["valley"].count == 1
    assert abs(s["valley"].length - math.sqrt(10**2 + 10**2 + 4**2)) < TOL


def test_pitch_recovered_from_normals():
    for f in hip_roof(40, 24, 6):
        assert abs(pitch_x12(f) - 6) < 0.05


def test_line_lengths_dict_shape_and_drip_edge():
    d = line_lengths_dict(hip_roof(40, 24, 6))
    assert d["ridge"]["count"] == 1
    assert d["hip"]["length_ft"] == pytest.approx(72.0, abs=TOL)
    # Drip edge = eaves + rakes; hip roof has no rakes, so == eaves.
    assert d["drip_edge"]["length_ft"] == pytest.approx(128.0, abs=TOL)


def test_edge_facet_aligns_with_engine_pitch():
    f = hip_roof(40, 24, 6)[0]
    # EdgeFacet exposes the engine's Pitch value object.
    assert f.pitch.x12 == pytest.approx(6.0, abs=0.05)
    assert 0.0 <= f.azimuth_deg < 360.0
    assert f.source == "geometry"

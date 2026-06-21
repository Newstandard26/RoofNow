"""BuildingModel contract, plane math, and the M1 facet service."""

import math

import pytest

from roofwall.cv.solar_dsm import Plane, lift, plane_from_segment
from roofwall.measurement.edges import make_facet
from roofwall.model import BuildingModel, Origin
from roofwall.sources.facets import building_model_for, sample_building_model


def test_building_model_to_dict_contract():
    m = sample_building_model()
    d = m.to_dict()
    assert set(d) == {"facets", "origin", "source", "notes"}
    assert set(d["origin"]) == {"lat", "lng"}
    f0 = d["facets"][0]
    assert set(f0) == {"id", "verts"}
    assert len(f0["verts"][0]) == 3  # [x, y, z]


def test_building_model_line_lengths_snapped():
    # The sample is the watertight cross-gable: 3 ridges, 2 valleys, 5 eaves.
    ll = sample_building_model().line_lengths()
    assert ll["ridge"]["count"] == 3
    assert ll["valley"]["count"] == 2
    assert ll["eave"]["count"] == 5


def test_building_model_for_address_keeps_synthetic_note():
    m = building_model_for(address="8656 Scott Lane, Machesney Park, IL")
    assert m.source == "synthetic"
    assert "not yet deployed" in (m.notes or "").lower()


def test_plane_from_segment_recovers_pitch_and_azimuth():
    # A 6/12 facet (pitch ~26.57 deg) facing south (azimuth 180).
    pitch_deg = math.degrees(math.atan(0.5))
    plane = plane_from_segment(pitch_deg, 180.0, (10.0, 10.0), 12.0)
    # Build a small polygon on the plane and check the recovered facet.
    poly = [(0, 0), (8, 0), (8, 6), (0, 6)]
    verts = [lift(x, y, plane) for x, y in poly]
    f = make_facet("seg", verts)
    assert f.pitch.x12 == pytest.approx(6.0, abs=0.02)
    assert f.azimuth_deg == pytest.approx(180.0, abs=0.5)


def test_plane_passes_through_center_height():
    plane = plane_from_segment(30.0, 90.0, (5.0, 7.0), 15.0)
    assert plane.z_at(5.0, 7.0) == pytest.approx(15.0)


def test_flat_segment_is_horizontal_plane():
    plane = plane_from_segment(0.0, 0.0, (0.0, 0.0), 9.0)
    assert plane.a == pytest.approx(0.0)
    assert plane.b == pytest.approx(0.0)
    assert plane.z_at(100.0, -50.0) == pytest.approx(9.0)


def test_from_edge_facets_roundtrip():
    facets = [make_facet("a", [(0, 0, 0), (1, 0, 0), (1, 1, 1)])]
    m = BuildingModel.from_edge_facets(facets, Origin(1.0, 2.0), "lidar", "x")
    assert m.source == "lidar"
    assert m.facets[0].id == "a"
    assert m.to_dict()["origin"] == {"lat": 1.0, "lng": 2.0}

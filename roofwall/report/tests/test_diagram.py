"""Roof diagram data from Solar segments and from 3D facets."""

from roofwall.measurement.edges import hip_roof
from roofwall.report.diagram import from_edge_facets, from_solar

SOLAR_PAYLOAD = {
    "center": {"latitude": 42.3483, "longitude": -89.0421},
    "solarPotential": {"roofSegmentStats": [
        {"pitchDegrees": 26.57, "azimuthDegrees": 180.0,
         "stats": {"areaMeters2": 50.0},
         "boundingBox": {"sw": {"latitude": 42.34825, "longitude": -89.04215},
                          "ne": {"latitude": 42.34835, "longitude": -89.04205}}},
        {"pitchDegrees": 26.57, "azimuthDegrees": 0.0,
         "stats": {"areaMeters2": 50.0},
         "boundingBox": {"sw": {"latitude": 42.34835, "longitude": -89.04215},
                          "ne": {"latitude": 42.34845, "longitude": -89.04205}}},
    ]},
}


def test_from_solar_shape():
    facets = from_solar(SOLAR_PAYLOAD)
    assert len(facets) == 2
    f = facets[0]
    assert len(f["poly"]) == 4 and len(f["poly"][0]) == 2
    assert f["facing"] == "S"           # azimuth 180
    assert f["pitch"] == "6/12"         # ~26.57 deg
    assert f["area_sqft"] > 0
    # north segment sits above the south one (greater y).
    assert max(p[1] for p in facets[1]["poly"]) > max(p[1] for p in facets[0]["poly"])


def test_from_solar_missing_bbox_skipped():
    payload = {"center": {"latitude": 42.0, "longitude": -89.0},
               "solarPotential": {"roofSegmentStats": [
                   {"pitchDegrees": 20, "azimuthDegrees": 90, "stats": {"areaMeters2": 10}}]}}
    assert from_solar(payload) == []


def test_from_edge_facets_hip():
    facets = from_edge_facets(hip_roof(40, 24, 6))
    assert len(facets) == 4
    assert all(len(f["poly"]) >= 3 for f in facets)
    assert {f["facing"] for f in facets}  # each has a cardinal facing

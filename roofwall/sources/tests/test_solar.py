"""Solar API parsing + client behaviour, fully offline (no key/network)."""

import math

import pytest

from roofwall.measurement.engine import Pitch, sqm_to_sqft
from roofwall.sources.solar import (
    CoverageError,
    SolarClient,
    SolarError,
    imagery_date_iso,
    imagery_quality,
    parse_building_insights,
    whole_roof_area_sqft,
)

# A minimal payload matching the documented buildingInsights shape:
# a simple 2-facet gable, both 18.43 deg (~4/12), ground area 100 m² each.
SAMPLE_PAYLOAD = {
    "solarPotential": {
        "roofSegmentStats": [
            {
                "pitchDegrees": 18.43,
                "azimuthDegrees": 180.0,
                "stats": {"areaMeters2": 105.4, "groundAreaMeters2": 100.0},
                "planeHeightAtCenterMeters": 5.0,
            },
            {
                "pitchDegrees": 18.43,
                "azimuthDegrees": 0.0,
                "stats": {"areaMeters2": 105.4, "groundAreaMeters2": 100.0},
                "planeHeightAtCenterMeters": 5.0,
            },
        ],
        "wholeRoofStats": {"areaMeters2": 210.8},
    }
}


def test_parse_building_insights_basic():
    report = parse_building_insights(SAMPLE_PAYLOAD)
    assert len(report.facets) == 2

    # 4/12-ish pitch from 18.43 deg.
    pitch = report.facets[0].pitch
    assert pitch.x12 == pytest.approx(4.0, abs=0.02)

    # 100 m² ground each -> sqft -> * multiplier sloped.
    expected_sloped = 2 * sqm_to_sqft(100.0) * pitch.multiplier
    assert report.total_sloped_sqft == pytest.approx(expected_sloped, rel=1e-6)


def test_parse_two_facets_get_simple_gable_waste():
    report = parse_building_insights(SAMPLE_PAYLOAD)
    assert report.waste_pct == pytest.approx(0.05)


def test_whole_roof_area_crosscheck():
    area = whole_roof_area_sqft(SAMPLE_PAYLOAD)
    assert area == pytest.approx(sqm_to_sqft(210.8))


def test_parse_infers_ground_area_when_missing():
    payload = {
        "solarPotential": {
            "roofSegmentStats": [
                {
                    "pitchDegrees": 18.43,
                    "azimuthDegrees": 90.0,
                    "stats": {"areaMeters2": 105.4},  # no groundAreaMeters2
                }
            ]
        }
    }
    report = parse_building_insights(payload)
    f = report.facets[0]
    # Recovered plan area * multiplier should reproduce ~the sloped area.
    assert f.sloped_area_sqft == pytest.approx(sqm_to_sqft(105.4), rel=1e-6)


def test_parse_errors_on_empty():
    with pytest.raises(SolarError):
        parse_building_insights({"solarPotential": {"roofSegmentStats": []}})
    with pytest.raises(SolarError):
        parse_building_insights({})


def test_client_uses_injected_http_and_parses():
    def fake_get(url, params=None, timeout=None):
        assert "buildingInsights:findClosest" in url
        assert params["key"] == "TEST_KEY"
        return SAMPLE_PAYLOAD

    client = SolarClient(api_key="TEST_KEY", http_get=fake_get)
    report = client.roof_report(38.8977, -77.0365)
    assert len(report.facets) == 2


def test_client_requires_key():
    client = SolarClient(api_key=None, http_get=lambda *a, **k: {})
    with pytest.raises(SolarError):
        client.building_insights(0, 0)


def test_suggest_addresses_parses_results():
    from roofwall.sources.geocode import suggest_addresses

    payload = {"status": "OK", "results": [
        {"formatted_address": "8656 Scott Ln, Machesney Park, IL 61115, USA",
         "geometry": {"location": {"lat": 42.3483, "lng": -89.0421}}, "place_id": "abc"},
        {"formatted_address": "8656 Scott Ln, Somewhere Else",
         "geometry": {"location": {"lat": 40.0, "lng": -80.0}}, "place_id": "def"},
    ]}
    out = suggest_addresses("8656 Scott", api_key="k",
                            http_get=lambda url, params=None, timeout=None: payload)
    assert len(out) == 2
    assert out[0]["description"].startswith("8656 Scott Ln, Machesney Park")
    assert out[0]["lat"] == 42.3483 and out[0]["lng"] == -89.0421


def test_suggest_addresses_continental_us_only():
    from roofwall.sources.geocode import suggest_addresses

    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured.update(params or {})
        return {"results": [
            {"formatted_address": "123 Main St, Rockford, IL",
             "geometry": {"location": {"lat": 42.27, "lng": -89.09}}},
            {"formatted_address": "Honolulu, HI", "geometry": {"location": {"lat": 21.31, "lng": -157.86}}},
            {"formatted_address": "Anchorage, AK", "geometry": {"location": {"lat": 61.22, "lng": -149.90}}},
        ]}

    out = suggest_addresses("123 Main", api_key="k", http_get=fake_get)
    # request is constrained to the US, and AK/HI are dropped by the CONUS bbox.
    assert captured.get("components") == "country:US"
    assert len(out) == 1
    assert out[0]["description"].startswith("123 Main St, Rockford")


def test_suggest_addresses_graceful():
    from roofwall.sources.geocode import suggest_addresses
    # short query, no key, and a throwing http_get all return [] (never raise).
    assert suggest_addresses("ab", api_key="k") == []
    assert suggest_addresses("123 Main St", api_key=None) == []

    def boom(*a, **k):
        raise RuntimeError("down")

    assert suggest_addresses("123 Main St", api_key="k", http_get=boom) == []


def test_imagery_date_and_quality_parsing():
    payload = {
        "imageryDate": {"year": 2023, "month": 6, "day": 5},
        "imageryQuality": "HIGH",
    }
    assert imagery_date_iso(payload) == "2023-06-05"
    assert imagery_quality(payload) == "HIGH"


def test_imagery_date_missing_is_none():
    assert imagery_date_iso({}) is None
    assert imagery_quality({}) is None


def test_client_404_raises_coverage_error():
    # Simulate the real requests path raising CoverageError on 404 by using
    # an http_get that mimics it.
    def fake_get(url, params=None, timeout=None):
        raise CoverageError("no coverage")

    client = SolarClient(api_key="K", http_get=fake_get)
    with pytest.raises(CoverageError):
        client.roof_report(0, 0)

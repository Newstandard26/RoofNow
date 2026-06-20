"""Application service: demo vs. live routing."""

import pytest

from roofwall.app import measure_address


def test_measure_address_demo_without_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    d = measure_address(address="742 Evergreen Terrace")
    assert d["mode"] == "demo"
    assert d["roof"]["total_squares"] > 0
    assert d["walls"]["net_siding_area_sqft"] > 0
    assert "facets" in d


def test_measure_address_by_latlng_demo(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    d = measure_address(lat=38.8977, lng=-77.0365)
    assert d["mode"] == "demo"
    assert d["address"]  # synthesized label from coords


def test_live_failure_degrades_to_demo(monkeypatch):
    # Key present but the Solar call will fail (no network/fake key) -> demo.
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "definitely-not-valid")

    import roofwall.app as app

    def boom(*a, **k):
        raise RuntimeError("solar down")

    monkeypatch.setattr(app, "_live_report", boom)
    d = measure_address(address="123 Anywhere")
    assert d["mode"] == "demo"
    assert "note" in d and "demo data" in d["note"].lower()


def test_live_report_with_injected_solar(monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "k")
    # Patch the live path to exercise the dict assembly deterministically.
    import roofwall.app as app
    from roofwall.measurement.engine import Pitch, measure_facet, summarize_roof
    from roofwall.report.render import report_to_dict

    def fake_live(address, lat, lng, *, waste_pct, key):
        facets = [
            measure_facet(footprint_area_sqft=1000, pitch=Pitch.from_x12(6), azimuth_deg=180),
            measure_facet(footprint_area_sqft=1000, pitch=Pitch.from_x12(6), azimuth_deg=0),
        ]
        rd = report_to_dict(summarize_roof(facets, waste_pct=0.1))
        return {"mode": "live", "address": address, "roof": rd["roof"],
                "facets": rd["facets"], "walls": {"net_siding_area_sqft": 1}}

    monkeypatch.setattr(app, "_live_report", fake_live)
    d = measure_address(address="1 Real St")
    assert d["mode"] == "live"
    assert d["roof"]["facet_count"] == 2

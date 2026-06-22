"""Application service: demo vs. live routing."""

import pytest

from roofwall.app import measure_address


def test_measure_address_demo_without_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    d = measure_address(address="742 Evergreen Terrace")
    assert d["mode"] == "demo"
    assert d["demo_reason"] == "no_api_key"
    assert d["roof"]["total_squares"] > 0
    assert d["walls"]["net_siding_area_sqft"] > 0
    assert "facets" in d


@pytest.mark.parametrize(
    "exc,expected",
    [
        ("GeocodeError:ZERO_RESULTS", "geocode_failed: ZERO_RESULTS"),
        ("CoverageError", "solar_not_covered"),
        ("SolarError:Solar API 403: denied", "solar_error: Solar API 403: denied"),
        ("ValueError:boom", "exception: boom"),
    ],
)
def test_demo_reason_categorizes_live_failures(monkeypatch, exc, expected):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "k")
    import roofwall.app as app
    from roofwall.sources.geocode import GeocodeError
    from roofwall.sources.solar import CoverageError, SolarError

    kind, _, msg = exc.partition(":")
    err = {
        "GeocodeError": GeocodeError,
        "CoverageError": CoverageError,
        "SolarError": SolarError,
        "ValueError": ValueError,
    }[kind]

    def boom(*a, **k):
        raise err(msg) if msg else err()

    monkeypatch.setattr(app, "_live_report", boom)
    d = measure_address(address="anywhere")
    assert d["mode"] == "demo"
    assert d["demo_reason"] == expected


def test_recover_via_service_ok(monkeypatch):
    monkeypatch.setenv("ROOFWALL_CV_URL", "https://cv.example.com")
    from roofwall.app import recover_line_lengths

    def fake_get(url, params):
        assert url.endswith("/facets")
        return {"line_lengths": {"ridge": {"count": 1, "length_ft": 16}},
                "model": {"facets": [1, 2, 3, 4]}}

    ll, status = recover_line_lengths(42.0, -89.0, key="k", http_get=fake_get)
    assert ll["ridge"]["count"] == 1
    assert status == "ok:4"


def test_recover_via_service_error(monkeypatch):
    monkeypatch.setenv("ROOFWALL_CV_URL", "https://cv.example.com")
    from roofwall.app import recover_line_lengths

    def boom(url, params):
        raise RuntimeError("cv down")

    ll, status = recover_line_lengths(42.0, -89.0, key="k", http_get=boom)
    assert ll is None
    assert status.startswith("error:")


def test_recover_in_process_is_graceful(monkeypatch):
    # No service URL -> in-process attempt. Must never raise; with no real
    # network/key it returns a non-ok status string (deps_missing/no_dsm/error).
    monkeypatch.delenv("ROOFWALL_CV_URL", raising=False)
    from roofwall.app import recover_line_lengths

    ll, status = recover_line_lengths(42.0, -89.0, key="bad")
    assert ll is None
    assert isinstance(status, str) and not status.startswith("ok")


def test_recover_geometry_in_process_returns_real_diagram(monkeypatch):
    # Light path returns a model -> geometry payload has real per-facet polys
    # (not bounding-box rectangles) plus the Length Diagram.
    monkeypatch.delenv("ROOFWALL_CV_URL", raising=False)
    import roofwall.app as app
    from roofwall.measurement.edges import hip_roof
    from roofwall.model import BuildingModel, Origin

    model = BuildingModel.from_edge_facets(hip_roof(40, 24, 6),
                                           Origin(42.0, -89.0), "solar-dsm")
    monkeypatch.setattr("roofwall.cv.light.build_model_light",
                        lambda lat, lng, key: model)
    g = app.recover_geometry(42.0, -89.0, key="k")
    assert g["recovery_status"] == "ok:4"
    assert len(g["roof_diagram"]) == 4
    assert all(len(f["poly"]) >= 3 for f in g["roof_diagram"])
    assert g["line_lengths"]["ridge"]["count"] == 1
    assert g["line_lengths"]["hip"]["count"] == 4


def test_recover_geometry_graceful_on_error(monkeypatch):
    monkeypatch.delenv("ROOFWALL_CV_URL", raising=False)
    import roofwall.app as app

    def boom(lat, lng, key):
        raise RuntimeError("no network")

    monkeypatch.setattr("roofwall.cv.light.build_model_light", boom)
    g = app.recover_geometry(42.0, -89.0, key="k")
    assert g["roof_diagram"] is None
    assert g["line_lengths"] is None
    assert g["recovery_status"].startswith("error:")


def test_recover_geometry_via_service(monkeypatch):
    monkeypatch.setenv("ROOFWALL_CV_URL", "https://cv.example.com")
    import roofwall.app as app
    from roofwall.measurement.edges import hip_roof
    from roofwall.model import BuildingModel, Origin

    model = BuildingModel.from_edge_facets(hip_roof(40, 24, 6),
                                           Origin(42.0, -89.0), "solar-dsm")

    def fake_get(url, params):
        assert url.endswith("/facets")
        return {"model": model.to_dict(), "line_lengths": model.line_lengths()}

    g = app.recover_geometry(42.0, -89.0, key="k", http_get=fake_get)
    assert g["recovery_status"] == "ok:4"
    assert len(g["roof_diagram"]) == 4
    assert g["line_lengths"]["hip"]["count"] == 4


def test_live_report_includes_recovery_status(monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "k")
    import roofwall.app as app
    from roofwall.sources.solar import SolarClient

    payload = {"solarPotential": {"roofSegmentStats": [
        {"pitchDegrees": 26.57, "azimuthDegrees": 180.0,
         "stats": {"areaMeters2": 55.9, "groundAreaMeters2": 50.0}}]}}
    client = SolarClient(api_key="k", http_get=lambda *a, **k: payload)
    # recovery succeeds (mocked)
    monkeypatch.setattr(app, "recover_line_lengths",
                        lambda lat, lng, *, key: ({"ridge": {"count": 3}}, "ok:5"))
    res = app._live_report("1 A St", 42.0, -89.0, waste_pct=None, key="k", client=client)
    assert res["recovery_status"] == "ok:5"
    assert res["line_lengths"]["ridge"]["count"] == 3


def test_live_report_degrades_when_recovery_fails(monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "k")
    import roofwall.app as app
    from roofwall.sources.solar import SolarClient

    payload = {"solarPotential": {"roofSegmentStats": [
        {"pitchDegrees": 26.57, "azimuthDegrees": 180.0,
         "stats": {"areaMeters2": 55.9, "groundAreaMeters2": 50.0}}]}}
    client = SolarClient(api_key="k", http_get=lambda *a, **k: payload)
    monkeypatch.setattr(app, "recover_line_lengths",
                        lambda lat, lng, *, key: (None, "deps_missing:rasterio"))
    res = app._live_report("1 A St", 42.0, -89.0, waste_pct=None, key="k", client=client)
    # Report still renders; failure is visible, not blank.
    assert res["mode"] == "live"
    assert res["line_lengths"] is None
    assert res["recovery_status"] == "deps_missing:rasterio"
    assert res["roof"]["facet_count"] == 1


def test_live_debug_no_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    from roofwall.app import live_debug

    info = live_debug(address="1600 Amphitheatre Parkway")
    assert info["hasKey"] is False
    assert info["error"] == "no_api_key"


def test_live_debug_reports_status_with_injected_clients():
    from roofwall.app import live_debug
    from roofwall.sources.geocode import GeocodeResult
    from roofwall.sources.solar import SolarClient

    payload = {"solarPotential": {"roofSegmentStats": [
        {"pitchDegrees": 26.57, "azimuthDegrees": 180.0,
         "stats": {"areaMeters2": 55.9, "groundAreaMeters2": 50.0}}]}}

    class FakeGeo:
        def geocode(self, address):
            return GeocodeResult(lat=37.4220, lng=-122.0841, formatted_address=address)

    client = SolarClient(api_key="k", http_get=lambda *a, **k: payload)
    info = live_debug(address="1600 Amphitheatre Parkway", api_key="k",
                      client=client, geocoder=FakeGeo())
    assert info["hasKey"] is True
    assert info["geocode"] == "ok"
    assert info["lat"] == pytest.approx(37.4220)
    assert info["solar_http_status"] == 200
    # Diagnostics expose hasKey as a boolean, never the key value itself.
    assert info["hasKey"] in (True, False)
    assert "api_key" not in info and "key" not in info


def test_solar_http_status_maps_errors():
    from roofwall.app import _solar_http_status
    from roofwall.sources.solar import CoverageError, SolarClient, SolarError

    def cov(*a, **k):
        raise CoverageError("no coverage (404)")

    def err(*a, **k):
        raise SolarError("Solar API 403: PERMISSION_DENIED")

    assert _solar_http_status(SolarClient(api_key="k", http_get=cov), 0, 0) == 404
    assert _solar_http_status(SolarClient(api_key="k", http_get=err), 0, 0) == 403


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
    assert d["demo_reason"] == "exception: solar down"


def test_live_report_surfaces_imagery_date_and_source():
    # Inject a SolarClient whose HTTP layer returns a captured-shape payload
    # (with imageryDate) — no key/network needed.
    from roofwall.app import _live_report
    from roofwall.sources.solar import SolarClient

    payload = {
        "imageryDate": {"year": 2023, "month": 6, "day": 5},
        "imageryQuality": "HIGH",
        "solarPotential": {
            "roofSegmentStats": [
                {"pitchDegrees": 26.57, "azimuthDegrees": 180.0,
                 "stats": {"areaMeters2": 55.9, "groundAreaMeters2": 50.0}},
                {"pitchDegrees": 26.57, "azimuthDegrees": 0.0,
                 "stats": {"areaMeters2": 55.9, "groundAreaMeters2": 50.0}},
            ]
        },
    }
    client = SolarClient(api_key="k", http_get=lambda *a, **k: payload)
    res = _live_report("8656 Scott Lane", 42.0, -89.0, waste_pct=None,
                       key="k", client=client)
    assert res["mode"] == "live"
    assert res["data_source"] == "Google Solar"
    assert res["imagery_date"] == "2023-06-05"
    assert res["imagery_quality"] == "HIGH"
    assert res["line_lengths"] is None        # no faked Length Diagram on live
    assert res["facets"][0]["pitch"] == "6/12"


def test_no_coverage_keeps_demo_badge(monkeypatch):
    # Solar 404 (SolarNotCovered) must fall back to demo, mode stays "demo".
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "k")
    import roofwall.app as app
    from roofwall.sources.solar import CoverageError

    def boom(*a, **k):
        raise CoverageError("no coverage")

    monkeypatch.setattr(app, "_live_report", boom)
    d = measure_address(address="rural nowhere")
    assert d["mode"] == "demo"
    assert "data_source" not in d  # no live indicator on the fallback


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

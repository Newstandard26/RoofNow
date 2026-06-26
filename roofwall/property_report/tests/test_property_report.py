"""Property Intelligence Report — assembly, reuse, placeholders, failure mode."""
import pytest

from roofwall.property_report import build_property_report, validate_report
from roofwall.property_report.health import build_roof_health
from roofwall.property_report.recommendation import build_recommendation
from roofwall.property_report.storm import build_storm_exposure
from roofwall.property_report.summary import build_ai_summary, build_price_explanation


# --- a realistic measure_address-shaped report + matching quote --------------

def _report():
    return {
        "mode": "live",
        "address": "123 Main St, Rockford, IL 61101",
        "imagery_date": "2024-08-01",
        "data_source": "Google Solar",
        "lat": 42.27, "lng": -89.09,
        "roof": {
            "total_squares": 24.0, "order_squares": 27,
            "predominant_pitch": "6/12", "structure_complexity": "Normal",
            "facet_count": 6, "suggested_waste_pct": 21,
        },
    }


def _quote():
    return {
        "price_range": {"low": 14000, "high": 22000, "display": "$14,000 – $22,000"},
        "confidence": {"band": "high", "confidence_pct": 90,
                       "margin_of_error_pct": 8, "reasons": ["clean"], "warnings": []},
        "estimates": [{"key": "good"}, {"key": "better"}, {"key": "best"}],
        "measurement": {"order_squares": 27, "predominant_pitch": "6/12",
                        "structure_complexity": "Normal", "suggested_waste_pct": 21},
    }


# --- pure section builders ---------------------------------------------------

def test_ai_summary_grounded_in_data():
    s = build_ai_summary(_report(), _quote())
    assert "2,400 sq ft" in s["text"]          # 24 squares -> 2,400 sq ft
    assert "$14,000 – $22,000" in s["text"]
    assert any(h["label"] == "Pitch" for h in s["highlights"])


def test_price_explanation_lists_drivers():
    pe = build_price_explanation(_report(), _quote())
    labels = {d["label"] for d in pe["drivers"]}
    assert {"Roof size", "Pitch", "Complexity", "Waste factor"} <= labels


def test_placeholders_are_honest():
    h = build_roof_health(_report())
    st = build_storm_exposure(_report())
    assert h["available"] is False and h["checklist"]
    assert st["available"] is False


def test_recommendation_varies_with_confidence():
    hi = build_recommendation({"band": "high"}, found=True)
    lo = build_recommendation({"band": "low"}, found=False)
    assert hi["cta_label"] == lo["cta_label"] == "Schedule Free Roof Verification"
    assert hi["body"] != lo["body"]


# --- full report via build_property_report (patches measure/quote) -----------

def test_build_report_full(monkeypatch):
    import roofwall.app as app
    import roofwall.quote as quote
    monkeypatch.setattr(app, "measure_address", lambda **k: _report())
    monkeypatch.setattr(quote, "build_quote", lambda report, **k: _quote())

    r = build_property_report("123 Main St", lead={"first_name": "Jane", "last_name": "Roof",
                                                   "email": "j@x.co", "phone": "5551234567"})
    assert validate_report(r) == []                 # all required keys present
    assert r["status"] == "estimated"
    assert r["brand"]["name"] == "RoofNow"
    assert r["brand"]["powered_by"] == "New Standard Restoration"
    assert r["roof_snapshot"]["total_sloped_sqft"] == 2400
    assert r["quote"]["price_range"]["display"] == "$14,000 – $22,000"
    assert r["confidence"]["band"] == "high"
    assert r["roof_health"]["available"] is False
    assert r["storm_exposure"]["available"] is False
    assert r["recommended_next_step"]["cta_action"] == "book_inspection"
    assert r["lead"]["name"] == "Jane Roof"
    assert "subject to field verification" in r["disclaimer"]


def test_build_report_manual_review_when_measure_fails(monkeypatch):
    import roofwall.app as app
    def boom(**k):
        raise RuntimeError("solar down")
    monkeypatch.setattr(app, "measure_address", boom)

    r = build_property_report("nowhere")
    assert validate_report(r) == []
    assert r["status"] == "manual_review"
    assert r["quote"] is None
    assert r["confidence"]["band"] == "low"
    assert r["recommended_next_step"]["cta_action"] == "book_inspection"


def test_build_report_demo_is_manual_review(monkeypatch):
    import roofwall.app as app
    import roofwall.quote as quote
    demo = {**_report(), "mode": "demo", "demo_reason": "no_api_key"}
    monkeypatch.setattr(app, "measure_address", lambda **k: demo)
    monkeypatch.setattr(quote, "build_quote", lambda report, **k: _quote())

    r = build_property_report("123 Main St")
    assert r["status"] == "manual_review"           # demo/not-found -> manual review
    assert validate_report(r) == []

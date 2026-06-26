"""Property Intelligence Report — assembly, reuse, value sections, failure mode."""
import pytest

from roofwall.property_report import build_property_report, validate_report
from roofwall.property_report.health import build_roof_health
from roofwall.property_report.recommendation import build_recommendation
from roofwall.property_report.storm import build_storm_exposure
from roofwall.property_report.summary import build_ai_summary, build_price_explanation


def _report(mode="live"):
    return {
        "mode": mode,
        "address": "123 Main St, Rockford, IL 61101",
        "imagery_date": "2024-08-01",
        "imagery_quality": "MEDIUM",
        "data_source": "Google Solar",
        "lat": 42.27, "lng": -89.09,
        "roof": {
            "total_squares": 24.0, "order_squares": 27,
            "predominant_pitch": "6/12", "structure_complexity": "Normal",
            "facet_count": 6, "suggested_waste_pct": 21, "min_confidence": 0.9,
        },
    }


# Estimate-confidence-shaped quote confidence (customer model)
_CONF_OK = {"label": "Estimate Confidence", "level": "Excellent Estimate",
            "headline": "Excellent", "accuracy_pct": 5, "reliable": True}


def _quote():
    return {
        "price_range": {"low": 14000, "high": 22000, "display": "$14,000 – $22,000"},
        "confidence": _CONF_OK,
        "estimates": [{"key": "good"}, {"key": "better"}, {"key": "best"}],
        "measurement": {"order_squares": 27, "total_squares": 24.0,
                        "predominant_pitch": "6/12", "structure_complexity": "Normal",
                        "suggested_waste_pct": 21},
    }


# --- pure section builders ---------------------------------------------------

def test_ai_summary_is_success_framed():
    s = build_ai_summary(_report(), _quote())
    assert "24 squares" in s["text"]
    assert "6/12" in s["text"]
    # no failure language
    low = s["text"].lower()
    assert "couldn't" not in low and "low confidence" not in low and "failed" not in low
    assert any(h["label"] == "Pitch" for h in s["highlights"])


def test_price_explanation_homeowner_language():
    pe = build_price_explanation(_report(), _quote())
    labels = {d["label"] for d in pe["drivers"]}
    assert {"Roof size", "Roof complexity", "Material quality", "Labor & accessories"} <= labels
    # no engineering jargon
    blob = " ".join(d["note"] for d in pe["drivers"]).lower()
    assert "polygon" not in blob and "valley" not in blob and "ridge" not in blob


def test_sections_are_value_add_not_placeholders():
    h = build_roof_health(_report())
    st = build_storm_exposure(_report())
    assert h["available"] is True
    assert "verify" in h["headline"].lower()
    assert h["checklist"]
    assert st["available"] is True
    assert "hail" in st["message"].lower()


def test_recommendation_success_framed_with_checklist():
    rec = build_recommendation(_CONF_OK, found=True)
    assert rec["cta_label"] == "Schedule Free Roof Verification"
    assert rec["headline"] == "Your estimate is ready"
    assert "Verify measurements" in rec["checklist"]
    assert "no obligation" in rec["free_no_obligation"].lower()


# --- full report (real build_quote; only measure_address patched) ------------

def test_build_report_full(monkeypatch):
    import roofwall.app as app
    monkeypatch.setattr(app, "measure_address", lambda **k: _report())

    r = build_property_report("123 Main St", lead={"first_name": "Jane", "last_name": "Roof",
                                                   "email": "j@x.co", "phone": "5551234567"})
    assert validate_report(r) == []
    assert r["status"] == "estimated"
    assert r["confidence"]["label"] == "Estimate Confidence"
    assert r["confidence"]["level"] in ("Excellent Estimate", "Very Good Estimate")
    assert r["confidence"]["reliable"] is True
    # engineering confidence stored internally (float), not a customer band
    assert isinstance(r["engineering_confidence"], float)
    assert r["roof_snapshot"]["total_sloped_sqft"] == 2400
    assert r["quote"]["price_range"]["low"] > 0
    assert r["roof_health"]["available"] is True
    assert r["storm_exposure"]["available"] is True
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
    assert r["confidence"]["level"] == "Manual Review Recommended"
    assert r["confidence"]["reliable"] is False
    assert r["engineering_confidence"] is None
    # even failure copy stays positive
    assert "failed" not in r["ai_summary"]["text"].lower()


def test_build_report_demo_is_manual_review(monkeypatch):
    import roofwall.app as app
    monkeypatch.setattr(app, "measure_address", lambda **k: _report(mode="demo"))
    r = build_property_report("123 Main St")
    assert r["status"] == "manual_review"
    assert r["confidence"]["level"] == "Manual Review Recommended"
    assert validate_report(r) == []

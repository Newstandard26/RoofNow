"""Branded proposal PDF — builds valid multi-page bytes, degrades gracefully."""
import pytest

from roofwall.proposal import COMPANY, build_proposal_pdf
from roofwall.sources.streetview import street_view_image


def _report():
    return {
        "property": {"address": "4150 N Rockton Ave, Rockford, IL 61101"},
        "roof_snapshot": {"total_squares": 27.0, "total_sloped_sqft": 2700,
                          "predominant_pitch": "6/12", "structure_complexity": "Normal"},
        "property_details": {"year_built": 1998, "roof_cover": "Asphalt"},
        "confidence": {"level": "Excellent Estimate", "accuracy_text": "within approximately ±5%"},
        "disclaimer": "Budgetary and subject to field verification.",
        "quote": {"estimates": [
            {"key": "good", "name": "Good", "price_display": "$14,000 – $18,000",
             "price": 16000, "price_per_square": 520, "features": ["A", "B", "C"]},
            {"key": "better", "name": "Better", "price_display": "$17,000 – $22,000",
             "price": 19500, "price_per_square": 620, "features": ["A", "B", "C"]},
            {"key": "best", "name": "Best", "price_display": "$21,000 – $27,000",
             "price": 24000, "price_per_square": 740, "features": ["A", "B", "C"]},
        ]},
    }


def _pages(pdf: bytes) -> int:
    # crude page count: '/Type /Page' occurrences (not /Pages)
    import re
    return len(re.findall(rb"/Type\s*/Page[^s]", pdf))


def test_pdf_is_valid_and_multipage():
    pdf = build_proposal_pdf(_report(), {"first_name": "Matt", "last_name": "Downey",
                                         "email": "m@x.co", "phone": "(815) 555-1212"})
    assert isinstance(pdf, (bytes, bytearray))
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 5000
    assert _pages(pdf) == 4


def test_pdf_without_customer_name_or_data():
    # missing name -> "Homeowner"; empty report still renders (no crash)
    pdf = build_proposal_pdf({"quote": {"estimates": []}}, {})
    assert pdf[:5] == b"%PDF-"
    assert _pages(pdf) == 4


def test_company_branding_defaults():
    assert COMPANY["name"] == "New Standard Restoration, LLC"
    assert "104.020070" in COMPANY["license"]
    assert COMPANY["certification"] == "Owens Corning Preferred Contractor"
    assert len(COMPANY["scope_of_work"]) >= 6


def test_street_view_no_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    assert street_view_image("1 Main St, Town, IL") is None


def test_street_view_success(monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "k")
    def fake_get(url, params, *, expect_json):
        if expect_json:
            return 200, {"status": "OK"}
        return 200, b"\xff\xd8\xff" + b"x" * 4000   # jpeg-ish bytes
    img = street_view_image("1 Main St, Town, IL", http_get=fake_get)
    assert isinstance(img, bytes) and len(img) > 1500


def test_street_view_zero_results(monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "k")
    def fake_get(url, params, *, expect_json):
        return 200, {"status": "ZERO_RESULTS"}
    assert street_view_image("nowhere", http_get=fake_get) is None

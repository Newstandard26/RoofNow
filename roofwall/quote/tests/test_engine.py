"""Instant-quote engine — measurement report -> consumer quote dict."""
import pytest

from roofwall.quote.engine import BRAND, POWERED_BY, build_preview, build_quote


def _live_report():
    """A realistic measure_address-shaped report for a clean 6/12 hip roof."""
    return {
        "mode": "live",
        "address": "123 Main St, Springfield",
        "imagery_date": "2024-08-01",
        "recovery_status": "ok:6",
        "line_lengths": {"ridge": {"length_ft": 40, "count": 1},
                         "hip": {"length_ft": 60, "count": 4}},
        "roof": {
            "total_squares": 24.0,
            "order_squares": 27,
            "predominant_pitch": "6/12",
            "structure_complexity": "Normal",
            "facet_count": 6,
            "facets_needing_qa": 0,
            "min_confidence": 0.9,
            "suggested_waste_pct": 21,
        },
    }


def test_build_quote_shape():
    q = build_quote(_live_report())
    assert q["brand"] == BRAND
    assert q["powered_by"] == POWERED_BY
    assert q["address"] == "123 Main St, Springfield"
    assert len(q["estimates"]) == 3
    assert [e["key"] for e in q["estimates"]] == ["good", "better", "best"]
    # Customer-facing confidence is Estimate Confidence (level, not a band/%).
    assert q["confidence"]["label"] == "Estimate Confidence"
    assert q["confidence"]["level"] == "Excellent Estimate"
    assert q["confidence"]["reliable"] is True
    assert q["estimate_confidence"]["level"] == "Excellent Estimate"
    # engineering confidence stored internally as a 0-1 float, never a band
    assert isinstance(q["engineering_confidence"], float)
    # order squares now derives from the admin waste setting (24 * 1.21 Normal)
    assert q["measurement"]["order_squares"] == pytest.approx(29.04, abs=0.1)
    assert q["price_range"]["low"] > 0
    assert q["price_range"]["high"] >= q["price_range"]["low"]
    assert POWERED_BY in q["disclaimer"]


def test_noisier_measurement_widens_range_but_stays_reliable():
    clean = build_quote(_live_report())
    noisy_report = _live_report()
    noisy_report["recovery_status"] = "low_confidence:6"
    noisy_report["roof"]["facets_needing_qa"] = 6
    noisy_report["roof"]["min_confidence"] = 0.3   # messy polygons
    noisy = build_quote(noisy_report)

    clean_better = next(e for e in clean["estimates"] if e["key"] == "better")
    noisy_better = next(e for e in noisy["estimates"] if e["key"] == "better")
    clean_span = clean_better["price_high"] - clean_better["price_low"]
    noisy_span = noisy_better["price_high"] - noisy_better["price_low"]
    assert noisy_span > clean_span
    # messy geometry must NOT read as "low" — the estimate is still trustworthy
    assert noisy["confidence"]["reliable"] is True
    assert noisy["confidence"]["level"] in ("Excellent Estimate", "Very Good Estimate")


def test_order_squares_falls_back_to_waste_grossup():
    report = _live_report()
    del report["roof"]["order_squares"]
    q = build_quote(report)
    # 24 squares * 1.21 waste ~= 29.04
    assert q["measurement"]["order_squares"] == pytest.approx(29.04, abs=0.1)
    assert q["price_range"]["low"] > 0


def test_preview_has_confidence_but_no_prices():
    p = build_preview(_live_report())
    assert p["brand"] == BRAND and p["powered_by"] == POWERED_BY
    assert p["found"] is True
    assert p["ready"] is True
    assert p["headline"] == "We found your roof"
    assert p["confidence"]["level"] == "Excellent Estimate"
    assert p["roof"]["total_squares"] == 24.0
    # pricing stays gated — no Good/Better/Best leaks into the teaser
    assert "estimates" not in p
    assert "price_range" not in p


def test_preview_demo_not_found_but_ready():
    report = _live_report()
    report["mode"] = "demo"
    report["demo_reason"] = "no_api_key"
    p = build_preview(report)
    assert p["found"] is False
    assert p["ready"] is True
    assert p["headline"] == "We located your property"
    assert "estimates" not in p


def test_demo_report_is_manual_review():
    report = _live_report()
    report["mode"] = "demo"
    report["demo_reason"] = "no_api_key"
    q = build_quote(report)
    assert q["confidence"]["level"] == "Manual Review Recommended"
    assert q["confidence"]["reliable"] is False
    assert len(q["estimates"]) == 3
    assert q["price_range"]["low"] > 0

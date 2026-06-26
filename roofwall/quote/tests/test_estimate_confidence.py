"""Estimate Confidence — customer-facing model (Phase 2.1)."""
import pytest

from roofwall.quote.estimate_confidence import assess_estimate


def _live(**roof):
    base = {"total_squares": 24.0, "predominant_pitch": "6/12",
            "structure_complexity": "Normal", "facet_count": 6, "min_confidence": 0.9}
    base.update(roof)
    return {"mode": "live", "imagery_quality": "MEDIUM", "roof": base}


def test_clean_live_roof_is_excellent():
    c = assess_estimate(_live())
    assert c.level == "Excellent Estimate"
    assert c.accuracy_pct == 5
    assert c.reliable is True
    d = c.to_dict()
    assert d["label"] == "Estimate Confidence"
    assert d["accuracy_text"] == "within approximately ±5%"
    # never expose a bare low percentage / band
    assert "band" not in d and "confidence_pct" not in d


def test_messy_geometry_still_reliable():
    # Low per-facet confidence (messy polygons) must NOT tank the estimate —
    # Solar area is still reliable. This is the core Phase 2.1 behavior.
    c = assess_estimate(_live(min_confidence=0.3))
    assert c.reliable is True
    assert c.level in ("Excellent Estimate", "Very Good Estimate")
    assert c.accuracy_pct <= 8


def test_low_imagery_softens_but_stays_reliable():
    r = _live()
    r["imagery_quality"] = "LOW"
    c = assess_estimate(r)
    assert c.reliable is True
    assert c.level in ("Excellent Estimate", "Very Good Estimate")


def test_missing_pitch_lowers_score():
    hi = assess_estimate(_live()).score
    lo = assess_estimate(_live(predominant_pitch=None)).score
    assert lo < hi


def test_demo_or_no_area_is_manual_review():
    assert assess_estimate({"mode": "demo", "roof": {"total_squares": 24}}).level == "Manual Review Recommended"
    assert assess_estimate({"mode": "live", "roof": {"total_squares": 0}}).level == "Manual Review Recommended"
    assert assess_estimate({}).reliable is False


def test_weights_sum_to_one():
    from roofwall.quote.estimate_confidence import WEIGHTS
    assert round(sum(WEIGHTS.values()), 6) == 1.0

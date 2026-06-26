"""Confidence engine — honest verdict from measurement QA signals."""
import pytest

from roofwall.quote.confidence import assess


def _report(**roof_and_top):
    """Tiny helper: split keys into roof.* vs top-level."""
    roof_keys = {
        "facet_count", "facets_needing_qa", "min_confidence",
        "structure_complexity", "total_squares", "order_squares",
        "predominant_pitch", "suggested_waste_pct",
    }
    roof = {k: v for k, v in roof_and_top.items() if k in roof_keys}
    top = {k: v for k, v in roof_and_top.items() if k not in roof_keys}
    top["roof"] = roof
    return top


def test_clean_recovery_is_high():
    c = assess(_report(
        mode="live", recovery_status="ok:6", line_lengths={"ridge": {}},
        facet_count=6, facets_needing_qa=0, min_confidence=0.9,
        structure_complexity="Simple",
    ))
    assert c.band == "high"
    assert c.confidence_pct >= 85
    assert c.margin_of_error_pct <= 0.12
    assert c.reasons
    assert c.warnings == ()


def test_review_status_is_medium_with_warning():
    c = assess(_report(
        mode="live", recovery_status="review:4", line_lengths={"ridge": {}},
        facet_count=8, facets_needing_qa=4, min_confidence=0.7,
        structure_complexity="Normal",
    ))
    assert c.band == "medium"
    assert any("review" in w.lower() for w in c.warnings)


def test_no_polygons_is_low_and_warns_footprint():
    c = assess(_report(
        mode="live", recovery_status="no_polygons",
        facet_count=0, facets_needing_qa=0,
    ))
    assert c.band == "low"
    assert c.margin_of_error_pct >= 0.20
    assert any("footprint" in w.lower() for w in c.warnings)


def test_demo_mode_is_low_with_sample_warning():
    c = assess(_report(mode="demo", demo_reason="no_api_key",
                       recovery_status="ok:6", facet_count=6))
    assert c.band == "low"
    assert any("sample" in w.lower() for w in c.warnings)


def test_complex_roof_adds_warning():
    c = assess(_report(
        mode="live", recovery_status="ok:14", line_lengths={"valley": {}},
        facet_count=14, facets_needing_qa=0, min_confidence=0.88,
        structure_complexity="Complex",
    ))
    assert any("complex" in w.lower() for w in c.warnings)


def test_confidence_bounded_and_margin_feeds_pricing():
    c = assess(_report(
        mode="live", recovery_status="low_confidence:2",
        facet_count=2, facets_needing_qa=2, min_confidence=0.3,
    ))
    assert 35 <= c.confidence_pct <= 99
    assert c.margin_of_error_pct > 0
    d = c.to_dict()
    assert d["margin_of_error_pct"] == round(c.margin_of_error_pct * 100)
    assert isinstance(d["reasons"], list) and isinstance(d["warnings"], list)

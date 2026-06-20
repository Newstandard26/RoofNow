"""Report serialization."""

import pytest

from roofwall.measurement.engine import FacetMeasurement, Pitch, measure_facet, summarize_roof
from roofwall.report.render import azimuth_to_cardinal, report_to_dict, report_to_text


def _report():
    facets = [
        measure_facet(footprint_area_sqft=1000.0, pitch=Pitch.from_x12(6), azimuth_deg=180),
        measure_facet(footprint_area_sqft=1000.0, pitch=Pitch.from_x12(6), azimuth_deg=0),
    ]
    return summarize_roof(facets, waste_pct=0.10)


@pytest.mark.parametrize(
    "deg,card",
    [(0, "N"), (45, "NE"), (90, "E"), (135, "SE"), (180, "S"),
     (225, "SW"), (270, "W"), (315, "NW"), (359, "N"), (370, "N")],
)
def test_azimuth_to_cardinal(deg, card):
    assert azimuth_to_cardinal(deg) == card


def test_report_to_dict_shape():
    d = report_to_dict(_report(), meta={"address": "x"})
    assert d["roof"]["facet_count"] == 2
    assert d["roof"]["order_squares"] >= d["roof"]["total_squares"]
    assert len(d["facets"]) == 2
    assert d["facets"][0]["facing"] == "S"
    assert d["meta"]["address"] == "x"


def test_report_to_text_contains_totals():
    text = report_to_text(_report(), address="123 Main")
    assert "ROOF MEASUREMENT REPORT" in text
    assert "123 Main" in text
    assert "Squares to order" in text


def test_qa_flag_rendered():
    low = FacetMeasurement(
        pitch=Pitch.from_x12(6), azimuth_deg=180.0,
        footprint_area_sqft=1000.0, sloped_area_sqft=1118.0,
        squares=11.18, confidence=0.4, source="lidar",
    )
    report = summarize_roof([low], waste_pct=0.10)
    text = report_to_text(report)
    assert "human QA" in text
    assert report_to_dict(report)["roof"]["facets_needing_qa"] == 1

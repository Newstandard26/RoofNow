"""Deterministic demo report generation."""

import pytest

from roofwall.sources.demo import ARCHETYPES, demo_full_report


def test_demo_report_shape():
    d = demo_full_report("123 Demo Street")
    assert d["mode"] == "demo"
    assert d["roof"]["total_squares"] > 0
    assert len(d["facets"]) >= 2
    assert set(d["walls"]["by_direction_sqft"]) == {"N", "E", "S", "W"}
    assert d["walls"]["net_siding_area_sqft"] > 0


def test_demo_is_deterministic():
    a = demo_full_report("100 Main St, Springfield")
    b = demo_full_report("100 Main St, Springfield")
    assert a == b


def test_demo_varies_by_address():
    squares = {
        demo_full_report(f"{n} Elm St")["roof"]["total_squares"] for n in range(20)
    }
    # Different addresses should not all collapse to one value.
    assert len(squares) > 1


def test_demo_covers_all_archetypes():
    seen = set()
    for n in range(200):
        seen.add(demo_full_report(f"addr {n}")["archetype"])
    assert seen == {a.name for a in ARCHETYPES}


def test_demo_net_siding_less_than_gross():
    d = demo_full_report("1 Openings Ave")
    assert d["walls"]["openings_sqft"] > 0
    # Net (with +10% waste) subtracts openings from gross.
    assert d["walls"]["net_siding_area_sqft"] < d["walls"]["gross_wall_area_sqft"] * 1.10

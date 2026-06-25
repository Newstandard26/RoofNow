"""Pricing engine — Good/Better/Best from squares, pitch, complexity."""
import math

import pytest

from roofwall.quote.pricing import (
    DEFAULT_PRICING,
    complexity_multiplier,
    estimate_tiers,
    parse_pitch_rise,
    pitch_multiplier,
)


def test_parse_pitch_rise():
    assert parse_pitch_rise("6/12") == 6
    assert parse_pitch_rise("10 / 12") == 10
    assert parse_pitch_rise("12/12") == 12
    assert parse_pitch_rise(None) is None
    assert parse_pitch_rise("flat") is None


def test_pitch_multiplier_increases_with_steepness():
    m4 = pitch_multiplier(4)
    m6 = pitch_multiplier(6)
    m9 = pitch_multiplier(9)
    m12 = pitch_multiplier(12)
    assert m4 == 1.00
    assert m4 <= m6 <= m9 <= m12
    assert m12 > m4
    # unknown pitch -> neutral mid-slope, never cheaper than flat
    assert pitch_multiplier(None) >= 1.00


def test_complexity_multiplier_order():
    s = complexity_multiplier("Simple")
    n = complexity_multiplier("Normal")
    c = complexity_multiplier("Complex")
    assert s < n < c
    assert complexity_multiplier(None) == n  # default to Normal


def test_three_tiers_ordered_good_better_best():
    tiers = estimate_tiers(20.0, "6/12", "Normal")
    assert [t.key for t in tiers] == ["good", "better", "best"]
    assert tiers[0].price < tiers[1].price < tiers[2].price
    for t in tiers:
        assert t.price_low <= t.price <= t.price_high


def test_steeper_and_complex_costs_more():
    base = estimate_tiers(20.0, "4/12", "Simple")[1].price
    steep = estimate_tiers(20.0, "12/12", "Simple")[1].price
    complex_ = estimate_tiers(20.0, "4/12", "Complex")[1].price
    assert steep > base
    assert complex_ > base


def test_more_squares_costs_more():
    small = estimate_tiers(10.0, "6/12", "Normal")[1].price
    big = estimate_tiers(30.0, "6/12", "Normal")[1].price
    assert big > small


def test_margin_widens_range_but_not_point():
    tight = estimate_tiers(25.0, "6/12", "Normal", margin_pct=0.0)[1]
    wide = estimate_tiers(25.0, "6/12", "Normal", margin_pct=0.25)[1]
    assert wide.price == tight.price  # point estimate unchanged
    tight_span = tight.price_high - tight.price_low
    wide_span = wide.price_high - wide.price_low
    assert wide_span > tight_span


def test_minimum_job_price_floor():
    # A tiny roof still can't quote below the configured floor.
    tiers = estimate_tiers(1.0, "4/12", "Simple")
    for t in tiers:
        assert t.price >= DEFAULT_PRICING.minimum_job_price


def test_zero_squares_is_zero():
    tiers = estimate_tiers(0.0, None, None)
    for t in tiers:
        assert t.price == 0
        assert t.price_per_square == 0


def test_tier_to_dict_has_display():
    t = estimate_tiers(20.0, "6/12", "Normal")[0]
    d = t.to_dict()
    assert d["key"] == "good"
    assert "–" in d["price_display"]
    assert isinstance(d["features"], list) and d["features"]

"""Phase 3 pricing config: waste, accessories, financing, service-area."""
import pytest

from roofwall.quote.engine import _financing_teaser, _order_squares, _service_area_flag
from roofwall.quote.pricing import (
    DEFAULT_PRICING,
    config_from_dict,
    config_to_dict,
    estimate_tiers,
    monthly_payment,
)


def test_new_fields_round_trip():
    d = config_to_dict(DEFAULT_PRICING)
    for k in ("waste_defaults", "accessories", "financing", "service_area"):
        assert k in d
    cfg = config_from_dict(d)
    assert config_to_dict(cfg) == d


def test_partial_override_keeps_new_field_defaults():
    cfg = config_from_dict({"minimum_job_price": 5000})
    assert cfg.waste_defaults == DEFAULT_PRICING.waste_defaults
    assert cfg.financing == DEFAULT_PRICING.financing


def test_accessories_add_to_price():
    base = estimate_tiers(20.0, "6/12", "Normal")[1].price
    cfg = config_from_dict({
        "accessories": [
            {"label": "Ridge vent", "amount": 600, "unit": "flat", "tiers": []},
            {"label": "Per-sq upgrade", "amount": 10, "unit": "per_square", "tiers": ["better"]},
        ]
    })
    bumped = estimate_tiers(20.0, "6/12", "Normal", config=cfg)[1].price
    # better tier gets 600 flat + 10*20 per-square = +800 (before rounding)
    assert bumped > base


def test_accessory_tier_targeting():
    cfg = config_from_dict({"accessories": [
        {"label": "best only", "amount": 1000, "unit": "flat", "tiers": ["best"]}]})
    tiers = {t.key: t.price for t in estimate_tiers(20.0, "6/12", "Normal", config=cfg)}
    base = {t.key: t.price for t in estimate_tiers(20.0, "6/12", "Normal")}
    assert tiers["best"] > base["best"]
    assert tiers["good"] == base["good"]    # untouched


def test_order_squares_uses_config_waste():
    roof = {"total_squares": 20.0, "structure_complexity": "Complex", "order_squares": 21}
    # Complex default waste = 26% -> 20 * 1.26 = 25.2 (overrides measured 21)
    assert _order_squares(roof, DEFAULT_PRICING) == pytest.approx(25.2, abs=0.01)


def test_monthly_payment():
    # 20k at 9.99% over 120 months ~ $264/mo
    pay = monthly_payment(20000, 9.99, 120)
    assert 250 <= pay <= 280
    assert monthly_payment(0, 9.99, 120) is None
    assert monthly_payment(20000, 0, 120) == round(20000 / 120)   # 0% APR = simple split


def test_financing_teaser_gated():
    off = config_from_dict({"financing": {"enabled": False}})
    assert _financing_teaser(off, {"low": 20000}) is None
    on = config_from_dict({"financing": {"enabled": True, "apr": 9.99, "term_months": 120}})
    t = _financing_teaser(on, {"low": 20000})
    assert t and t["enabled"] and t["monthly"] > 0 and "/mo" in t["text"]


def test_service_area_flag():
    cfg = config_from_dict({"service_area": {"enabled": True, "states": ["IL"], "zip_prefixes": [],
                                             "message": "Outside our area"}})
    assert _service_area_flag(cfg, "123 Main St, Rockford, IL 61101, USA")["in_area"] is True
    out = _service_area_flag(cfg, "1 Palm Ave, Miami, FL 33101, USA")
    assert out["in_area"] is False and out["message"] == "Outside our area"
    # disabled -> no flag
    assert _service_area_flag(config_from_dict({}), "anywhere") is None

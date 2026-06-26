"""Editable pricing: JSON rate card round-trips and overrides defaults."""
import json

import pytest

from roofwall.quote.pricing import (
    DEFAULT_PRICING,
    config_from_dict,
    config_to_dict,
    estimate_tiers,
    load_pricing,
)


def test_round_trip():
    d = config_to_dict(DEFAULT_PRICING)
    cfg = config_from_dict(d)
    assert config_to_dict(cfg) == d


def test_partial_override_keeps_defaults():
    cfg = config_from_dict({"minimum_job_price": 9999})
    assert cfg.minimum_job_price == 9999
    assert cfg.tiers == DEFAULT_PRICING.tiers          # untouched
    assert cfg.complexity_multipliers == DEFAULT_PRICING.complexity_multipliers


def test_override_a_single_tier_rate_changes_price():
    base = estimate_tiers(20.0, "6/12", "Normal")[0].price
    cfg = config_from_dict({
        "tiers": [
            {"key": "good", "name": "Good", "blurb": "x", "rate_per_square": 999,
             "features": ["a"]},
            {"key": "better", "name": "Better", "blurb": "x", "rate_per_square": 1100,
             "features": ["a"]},
            {"key": "best", "name": "Best", "blurb": "x", "rate_per_square": 1300,
             "features": ["a"]},
        ]
    })
    bumped = estimate_tiers(20.0, "6/12", "Normal", config=cfg)[0].price
    assert bumped > base


def test_complexity_partial_merge():
    cfg = config_from_dict({"complexity_multipliers": {"Complex": 2.0}})
    assert cfg.complexity_multipliers["Complex"] == 2.0
    assert cfg.complexity_multipliers["Simple"] == 1.0   # default retained


def test_load_pricing_from_env_json(monkeypatch):
    monkeypatch.setenv("ROOFNOW_PRICING_JSON", json.dumps({"minimum_job_price": 4242}))
    monkeypatch.delenv("ROOFNOW_PRICING_FILE", raising=False)
    cfg = load_pricing()
    assert cfg.minimum_job_price == 4242


def test_load_pricing_from_file(tmp_path, monkeypatch):
    p = tmp_path / "rate.json"
    p.write_text(json.dumps({"base_spread_pct": 0.2}))
    monkeypatch.delenv("ROOFNOW_PRICING_JSON", raising=False)
    monkeypatch.setenv("ROOFNOW_PRICING_FILE", str(p))
    cfg = load_pricing()
    assert cfg.base_spread_pct == 0.2


def test_load_pricing_bad_json_falls_back(monkeypatch):
    monkeypatch.setenv("ROOFNOW_PRICING_JSON", "{not valid json")
    monkeypatch.delenv("ROOFNOW_PRICING_FILE", raising=False)
    cfg = load_pricing()
    assert cfg is DEFAULT_PRICING


def test_example_config_file_is_valid():
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    path = os.path.join(root, "pricing.config.example.json")
    with open(path, encoding="utf-8") as fh:
        cfg = config_from_dict(json.load(fh))
    # The shipped example equals the built-in defaults.
    assert config_to_dict(cfg) == config_to_dict(DEFAULT_PRICING)

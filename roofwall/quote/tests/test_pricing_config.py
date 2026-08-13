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


# --------------------------------------------------------------------------- #
# OC shingle widget fields (shingle / warranty / badges)
# --------------------------------------------------------------------------- #


def test_defaults_carry_oc_shingle_fields():
    by_key = {t.key: t for t in DEFAULT_PRICING.tiers}
    assert by_key["good"].shingle["slug"] == "oakridge"
    assert by_key["better"].shingle["slug"] == "trudefinition-duration"
    assert by_key["better"].shingle["extra_slugs"] == ["trudefinition-duration-designer"]
    assert by_key["best"].shingle["slug"] == "trudefinition-duration-flex"
    for t in DEFAULT_PRICING.tiers:
        assert t.shingle["view"] == "shingle"
        assert t.shingle["layout"] == "row"
        assert t.shingle["style"] == "default"
        assert t.warranty
    assert by_key["good"].badges == ()
    assert {b["label"] for b in by_key["better"].badges} == {"Most Popular", "Preferred Warranty"}
    assert {b["label"] for b in by_key["best"].badges} == {
        "Recommended", "Impact-Rated", "Preferred Warranty"}


def test_tier_estimate_to_dict_exposes_shingle_fields():
    est = {e.key: e.to_dict() for e in estimate_tiers(25.0, "6/12", "Normal")}
    assert est["good"]["shingle"]["slug"] == "oakridge"
    assert est["better"]["shingle"]["extra_slugs"] == ["trudefinition-duration-designer"]
    assert est["best"]["warranty"].startswith("OC Preferred Warranty")
    assert est["best"]["badges"][0] == {"label": "Recommended", "tone": "recommended"}
    assert est["good"]["badges"] == []


def test_legacy_tiers_without_shingle_fields_get_defaults():
    # A rate card saved before the OC fields existed: same keys, no shingle/
    # warranty/badges -> the defaults are grafted back on per key.
    cfg = config_from_dict({
        "tiers": [
            {"key": "good", "name": "Good", "blurb": "x", "rate_per_square": 500,
             "features": ["a"]},
            {"key": "better", "name": "Better", "blurb": "x", "rate_per_square": 600,
             "features": ["a"]},
            {"key": "best", "name": "Best", "blurb": "x", "rate_per_square": 700,
             "features": ["a"]},
        ]
    })
    by_key = {t.key: t for t in cfg.tiers}
    assert by_key["good"].shingle["slug"] == "oakridge"
    assert by_key["better"].warranty.startswith("OC Preferred Warranty")
    assert {b["label"] for b in by_key["best"].badges} == {
        "Recommended", "Impact-Rated", "Preferred Warranty"}


def test_explicit_null_shingle_disables_widget():
    cfg = config_from_dict({
        "tiers": [
            {"key": "good", "name": "Good", "blurb": "x", "rate_per_square": 500,
             "features": [], "shingle": None, "warranty": "", "badges": []},
        ]
    })
    t = cfg.tiers[0]
    assert t.shingle is None and t.warranty == "" and t.badges == ()
    d = estimate_tiers(25.0, "6/12", "Normal", config=cfg)[0].to_dict()
    assert d["shingle"] is None and d["badges"] == []


def test_shingle_normalization_fills_widget_params():
    cfg = config_from_dict({
        "tiers": [
            {"key": "good", "name": "Good", "blurb": "x", "rate_per_square": 500,
             "features": [], "shingle": {"slug": " berkshire "},
             "badges": [{"label": "Value Pick", "tone": "value"}, {"label": ""},
                        {"label": "Odd", "tone": "nonsense"}]},
        ]
    })
    t = cfg.tiers[0]
    assert t.shingle == {"slug": "berkshire", "name": "", "view": "shingle",
                         "layout": "row", "style": "default", "extra_slugs": []}
    # Blank labels dropped; unknown tones preserved as given (UI falls back).
    assert t.badges == ({"label": "Value Pick", "tone": "value"},
                        {"label": "Odd", "tone": "nonsense"})


def test_example_config_file_is_valid():
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    path = os.path.join(root, "pricing.config.example.json")
    with open(path, encoding="utf-8") as fh:
        cfg = config_from_dict(json.load(fh))
    # The shipped example equals the built-in defaults.
    assert config_to_dict(cfg) == config_to_dict(DEFAULT_PRICING)

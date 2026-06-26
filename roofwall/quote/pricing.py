"""Pricing engine — Good / Better / Best replacement estimates.

Takes the measured roof (order squares, predominant pitch, structure
complexity) and turns it into three installed-price tiers. The price for a
tier is::

    order_squares  x  base_rate_per_square[tier]  x  pitch_mult  x  complexity_mult

``order_squares`` already folds in the waste factor (see
:mod:`roofwall.report.eagleview`), so it is the quantity that actually gets
installed. Steeper and more cut-up roofs cost more per square (access, safety,
more flashing/waste), captured by the two multipliers.

The dollar figures in :data:`DEFAULT_PRICING` are editable defaults — national
ballpark installed costs for a full asphalt-shingle tear-off and replacement.
Swap in your real New Standard Restoration rate card by passing a custom
:class:`PricingConfig`; nothing else in the pipeline hard-codes a number.

Everything here is pure and deterministic so it can be unit-tested without the
measurement pipeline or any network call.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Tuple

# One roofing "square" = 100 sqft of roof surface (matches the measurement engine).
ROOFING_SQUARE_SQFT = 100.0


@dataclass(frozen=True)
class TierSpec:
    """A product tier: its display copy and base installed rate per square."""

    key: str
    name: str
    blurb: str
    rate_per_square: float
    features: Tuple[str, ...]


@dataclass(frozen=True)
class PricingConfig:
    """All the knobs the pricing engine uses. Defaults are ballpark national
    installed costs — replace ``tiers`` with your real rate card."""

    tiers: Tuple[TierSpec, ...]
    # Pitch steepness -> labor/access multiplier, keyed by lower-bound rise/12.
    # Looked up by largest threshold <= the roof's rise.
    pitch_multipliers: Tuple[Tuple[int, float], ...]
    # Structure complexity ("Simple"/"Normal"/"Complex") -> multiplier.
    complexity_multipliers: Dict[str, float]
    # Base +/- pricing spread (estimate uncertainty before confidence widening).
    base_spread_pct: float = 0.07
    # Floor applied to any non-zero estimate so trivial roofs aren't quoted at $0.
    minimum_job_price: float = 3500.0
    # --- Phase 3 (admin-dashboard editable) ---
    # Waste % by structure complexity (used to gross up squares to order).
    waste_defaults: Dict[str, int] = field(
        default_factory=lambda: {"Simple": 11, "Normal": 21, "Complex": 26})
    # Accessory allowances added to each tier's price. Each item:
    #   {"label": str, "amount": float, "unit": "flat"|"per_square",
    #    "tiers": [tier keys] or [] for all}
    accessories: Tuple[Dict[str, Any], ...] = ()
    # Financing teaser shown on the report (display-only monthly payment).
    financing: Dict[str, Any] = field(
        default_factory=lambda: {"enabled": False, "apr": 9.99, "term_months": 120})
    # Market / service-area gating (soft flag on out-of-area addresses).
    service_area: Dict[str, Any] = field(
        default_factory=lambda: {"enabled": False, "states": [], "zip_prefixes": [], "message": ""})


DEFAULT_PRICING = PricingConfig(
    tiers=(
        TierSpec(
            key="good",
            name="Good",
            blurb="Quality architectural shingles — a durable, budget-friendly replacement.",
            rate_per_square=475.0,
            features=(
                "Architectural (dimensional) asphalt shingles",
                "Synthetic underlayment",
                "New drip edge & pipe boots",
                "Standard manufacturer warranty",
            ),
        ),
        TierSpec(
            key="better",
            name="Better",
            blurb="Upgraded shingles and ventilation — our most popular package.",
            rate_per_square=585.0,
            features=(
                "Premium architectural shingles",
                "Ice & water shield at eaves and valleys",
                "Ridge vent for balanced attic ventilation",
                "Enhanced manufacturer system warranty",
            ),
        ),
        TierSpec(
            key="best",
            name="Best",
            blurb="Designer / impact-resistant system with the strongest warranty.",
            rate_per_square=735.0,
            features=(
                "Designer or Class 4 impact-resistant shingles",
                "Full ice & water shield underlayment upgrade",
                "Premium ridge cap, vents and flashing",
                "Top-tier transferable warranty",
            ),
        ),
    ),
    pitch_multipliers=(
        (0, 1.00),    # flat / low slope, walkable
        (5, 1.05),    # 5/12 - 7/12
        (8, 1.15),    # 8/12 - 9/12, harder to walk
        (10, 1.28),   # 10/12 - 12/12, steep, requires staging
        (13, 1.40),   # > 12/12, very steep
    ),
    complexity_multipliers={"Simple": 1.00, "Normal": 1.08, "Complex": 1.18},
)


# --------------------------------------------------------------------------- #
# Fully-editable pricing: load a rate card from JSON (env var or file) so the
# numbers can change with NO code edit or redeploy of the engine.
# --------------------------------------------------------------------------- #


def config_to_dict(config: PricingConfig) -> Dict:
    """Serialize a PricingConfig to a plain dict (round-trips with from_dict)."""
    return {
        "tiers": [
            {
                "key": t.key,
                "name": t.name,
                "blurb": t.blurb,
                "rate_per_square": t.rate_per_square,
                "features": list(t.features),
            }
            for t in config.tiers
        ],
        "pitch_multipliers": [[int(r), float(m)] for r, m in config.pitch_multipliers],
        "complexity_multipliers": dict(config.complexity_multipliers),
        "base_spread_pct": config.base_spread_pct,
        "minimum_job_price": config.minimum_job_price,
        "waste_defaults": dict(config.waste_defaults),
        "accessories": [dict(a) for a in config.accessories],
        "financing": dict(config.financing),
        "service_area": dict(config.service_area),
    }


def config_from_dict(data: Dict, *, base: PricingConfig = DEFAULT_PRICING) -> PricingConfig:
    """Build a PricingConfig from a (possibly partial) dict.

    Any key omitted falls back to ``base`` (the defaults), so an operator can
    override just the Good rate, or just the minimum, without restating the
    whole rate card. ``tiers``, when present, fully replaces the tier list.
    """
    if not isinstance(data, dict):
        raise ValueError("pricing config must be a JSON object")

    if "tiers" in data and data["tiers"] is not None:
        tiers = tuple(
            TierSpec(
                key=str(t["key"]),
                name=str(t.get("name", t["key"].title())),
                blurb=str(t.get("blurb", "")),
                rate_per_square=float(t["rate_per_square"]),
                features=tuple(t.get("features", ())),
            )
            for t in data["tiers"]
        )
    else:
        tiers = base.tiers

    if "pitch_multipliers" in data and data["pitch_multipliers"] is not None:
        pitch = tuple(sorted(
            (int(r), float(m)) for r, m in data["pitch_multipliers"]
        ))
    else:
        pitch = base.pitch_multipliers

    complexity = dict(base.complexity_multipliers)
    if isinstance(data.get("complexity_multipliers"), dict):
        complexity.update({k: float(v) for k, v in data["complexity_multipliers"].items()})

    waste = dict(base.waste_defaults)
    if isinstance(data.get("waste_defaults"), dict):
        waste.update({k: int(v) for k, v in data["waste_defaults"].items()})

    if "accessories" in data and data["accessories"] is not None:
        accessories = tuple(
            {
                "label": str(a.get("label", "")),
                "amount": float(a.get("amount", 0) or 0),
                "unit": "per_square" if a.get("unit") == "per_square" else "flat",
                "tiers": list(a.get("tiers", []) or []),
            }
            for a in data["accessories"]
        )
    else:
        accessories = base.accessories

    financing = dict(base.financing)
    if isinstance(data.get("financing"), dict):
        financing.update(data["financing"])
    service_area = dict(base.service_area)
    if isinstance(data.get("service_area"), dict):
        service_area.update(data["service_area"])

    return PricingConfig(
        tiers=tiers,
        pitch_multipliers=pitch,
        complexity_multipliers=complexity,
        base_spread_pct=float(data.get("base_spread_pct", base.base_spread_pct)),
        minimum_job_price=float(data.get("minimum_job_price", base.minimum_job_price)),
        waste_defaults=waste,
        accessories=accessories,
        financing=financing,
        service_area=service_area,
    )


# Default config-file path, relative to the repo root (two levels up from here).
_DEFAULT_PRICING_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "pricing.config.json"
)


def load_pricing() -> PricingConfig:
    """Resolve the active rate card. Precedence (first that exists wins):

      1. Supabase active config (admin dashboard) — when configured
      2. ``ROOFNOW_PRICING_JSON``  — inline JSON in an env var
      3. ``ROOFNOW_PRICING_FILE``  — path to a JSON file
      4. ``pricing.config.json``   — at the repo root, if present
      5. built-in :data:`DEFAULT_PRICING`

    Any parse/validation error falls back to the next source rather than breaking
    the quote endpoint (and logs to stderr).
    """
    try:
        from roofwall.quote import pricing_store

        store_dict = pricing_store.load_active_config_dict()
        if store_dict:
            return config_from_dict(store_dict)
    except Exception as exc:  # noqa: BLE001
        import sys
        print(f"[pricing] Supabase config load failed, falling back: {exc}", file=sys.stderr)

    inline = os.environ.get("ROOFNOW_PRICING_JSON")
    path = os.environ.get("ROOFNOW_PRICING_FILE") or _DEFAULT_PRICING_FILE
    try:
        if inline:
            return config_from_dict(json.loads(inline))
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                return config_from_dict(json.load(fh))
    except Exception as exc:  # noqa: BLE001
        import sys
        print(f"[pricing] failed to load custom rate card, using defaults: {exc}",
              file=sys.stderr)
    return DEFAULT_PRICING


@dataclass(frozen=True)
class TierEstimate:
    """A priced tier: point estimate plus a low/high range."""

    key: str
    name: str
    blurb: str
    features: Tuple[str, ...]
    price: int
    price_low: int
    price_high: int
    price_per_square: int

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "blurb": self.blurb,
            "features": list(self.features),
            "price": self.price,
            "price_low": self.price_low,
            "price_high": self.price_high,
            "price_per_square": self.price_per_square,
            "price_display": f"${self.price_low:,} – ${self.price_high:,}",
        }


def parse_pitch_rise(pitch_label: Optional[str]) -> Optional[int]:
    """Pull the rise out of a pitch label like ``"6/12"`` -> ``6``.

    Returns ``None`` when the label is missing or unparseable so callers can
    fall back to a neutral (medium) pitch assumption.
    """
    if not pitch_label:
        return None
    m = re.search(r"(\d+)\s*/\s*12", str(pitch_label))
    if m:
        return int(m.group(1))
    m = re.search(r"-?\d+", str(pitch_label))
    return int(m.group(0)) if m else None


def pitch_multiplier(rise: Optional[int], config: PricingConfig = DEFAULT_PRICING) -> float:
    """Labor/access multiplier for a roof pitch (rise per 12 run)."""
    if rise is None:
        rise = 6  # neutral, mid-slope assumption when pitch is unknown
    mult = config.pitch_multipliers[0][1]
    for threshold, value in config.pitch_multipliers:
        if rise >= threshold:
            mult = value
    return mult


def complexity_multiplier(
    complexity: Optional[str], config: PricingConfig = DEFAULT_PRICING
) -> float:
    """Multiplier for structure complexity (Simple / Normal / Complex)."""
    if not complexity:
        return config.complexity_multipliers.get("Normal", 1.08)
    return config.complexity_multipliers.get(complexity, 1.08)


def _round_to(value: float, step: int) -> int:
    return int(round(value / step) * step)


def _accessory_total(accessories, tier_key: str, order_squares: float) -> float:
    """Sum the accessory allowances that apply to a tier (flat + per-square)."""
    total = 0.0
    for a in accessories or ():
        tiers = a.get("tiers") or []
        if tiers and tier_key not in tiers:
            continue
        amount = float(a.get("amount", 0) or 0)
        total += amount * order_squares if a.get("unit") == "per_square" else amount
    return total


def monthly_payment(principal: float, apr: float, term_months: int) -> Optional[int]:
    """Standard amortized monthly payment, rounded. None if inputs invalid."""
    try:
        principal = float(principal)
        n = int(term_months)
        r = float(apr) / 100.0 / 12.0
    except (TypeError, ValueError):
        return None
    if principal <= 0 or n <= 0:
        return None
    if r <= 0:
        return int(round(principal / n))
    pay = principal * (r * (1 + r) ** n) / ((1 + r) ** n - 1)
    return int(round(pay))


def estimate_tiers(
    order_squares: float,
    pitch_label: Optional[str],
    complexity: Optional[str],
    *,
    margin_pct: float = 0.0,
    config: PricingConfig = DEFAULT_PRICING,
) -> List[TierEstimate]:
    """Price Good / Better / Best for a roof.

    ``order_squares`` is the waste-inclusive quantity to install. ``margin_pct``
    (e.g. ``0.15`` for +/-15%) is the confidence engine's margin of error; it
    widens the displayed range on top of the base pricing spread, so a
    low-confidence measurement reads as a wider quote.
    """
    rise = parse_pitch_rise(pitch_label)
    p_mult = pitch_multiplier(rise, config)
    c_mult = complexity_multiplier(complexity, config)
    spread = math.hypot(config.base_spread_pct, max(margin_pct, 0.0))

    out: List[TierEstimate] = []
    for spec in config.tiers:
        raw = order_squares * spec.rate_per_square * p_mult * c_mult
        raw += _accessory_total(config.accessories, spec.key, order_squares)
        if raw > 0:
            raw = max(raw, config.minimum_job_price)
        price = _round_to(raw, 100)
        low = _round_to(raw * (1.0 - spread), 100)
        high = _round_to(raw * (1.0 + spread), 100)
        per_sq = _round_to(spec.rate_per_square * p_mult * c_mult, 5) if order_squares else 0
        out.append(
            TierEstimate(
                key=spec.key,
                name=spec.name,
                blurb=spec.blurb,
                features=spec.features,
                price=price,
                price_low=low,
                price_high=high,
                price_per_square=per_sq,
            )
        )
    return out

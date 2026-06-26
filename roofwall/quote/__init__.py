"""RoofNow instant-quote package.

Phase 1 of the consumer instant-quote product: turn a measured roof into a
Good / Better / Best estimate with an honest confidence verdict.

    * :mod:`roofwall.quote.pricing`     — Good/Better/Best from squares/pitch/complexity
    * :mod:`roofwall.quote.confidence`  — confidence %, margin of error, reasons, warnings
    * :mod:`roofwall.quote.engine`      — measurement report -> instant quote dict

Reuses the existing measurement pipeline; adds no new measurement logic.
"""

from roofwall.quote.confidence import Confidence, assess
from roofwall.quote.engine import (
    BRAND,
    DISCLAIMER,
    POWERED_BY,
    build_preview,
    build_quote,
)
from roofwall.quote.funnel import (
    build_email,
    build_slack_blocks,
    funnel_lead,
    lead_to_webhook_payload,
)
from roofwall.quote.lead import validate_lead
from roofwall.quote.pricing import (
    DEFAULT_PRICING,
    PricingConfig,
    TierEstimate,
    TierSpec,
    complexity_multiplier,
    config_from_dict,
    config_to_dict,
    estimate_tiers,
    load_pricing,
    parse_pitch_rise,
    pitch_multiplier,
)

__all__ = [
    "assess",
    "Confidence",
    "build_quote",
    "build_preview",
    "BRAND",
    "POWERED_BY",
    "DISCLAIMER",
    "estimate_tiers",
    "parse_pitch_rise",
    "pitch_multiplier",
    "complexity_multiplier",
    "PricingConfig",
    "DEFAULT_PRICING",
    "TierEstimate",
    "TierSpec",
    "config_from_dict",
    "config_to_dict",
    "load_pricing",
    "validate_lead",
    "funnel_lead",
    "build_email",
    "build_slack_blocks",
    "lead_to_webhook_payload",
]

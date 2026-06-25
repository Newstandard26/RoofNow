"""Lead capture — validate and normalize an instant-quote lead.

Phase 1 lead capture is intentionally storage-agnostic: this module just
validates and shapes the lead record. The API layer (``api/lead.py``) decides
where it goes — log, email, CRM webhook (``LEAD_WEBHOOK_URL``), or a database
later. Keeping validation here makes it unit-testable without any I/O.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Accept 10+ digit phone numbers in any common formatting.
_PHONE_DIGITS_RE = re.compile(r"\D+")

_VALID_TIERS = {"good", "better", "best"}


def _clean(value: Any, limit: int = 200) -> str:
    return str(value or "").strip()[:limit]


def validate_lead(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Validate a lead submission.

    Returns ``(lead, errors)``. ``lead`` is the normalized record; when
    ``errors`` is non-empty the caller should reject with 400. Requires a name,
    a usable email or phone, and an address.
    """
    errors: List[str] = []

    name = _clean(payload.get("name"))
    email = _clean(payload.get("email")).lower()
    phone_raw = _clean(payload.get("phone"))
    phone_digits = _PHONE_DIGITS_RE.sub("", phone_raw)
    address = _clean(payload.get("address"), limit=300)
    tier = _clean(payload.get("tier")).lower()

    if not name:
        errors.append("Name is required.")
    if not address:
        errors.append("Property address is required.")

    has_email = bool(email)
    has_phone = bool(phone_digits)
    if not has_email and not has_phone:
        errors.append("An email or phone number is required.")
    if has_email and not _EMAIL_RE.match(email):
        errors.append("Email address looks invalid.")
    if has_phone and len(phone_digits) < 10:
        errors.append("Phone number looks too short.")

    if tier and tier not in _VALID_TIERS:
        # A bad tier isn't fatal — just drop it rather than block the lead.
        tier = ""

    lead: Dict[str, Any] = {
        "name": name,
        "email": email,
        "phone": phone_digits,
        "address": address,
        "tier": tier or None,
        "estimate_low": payload.get("estimate_low"),
        "estimate_high": payload.get("estimate_high"),
        "source": "roofnow_instant_quote",
    }
    return lead, errors

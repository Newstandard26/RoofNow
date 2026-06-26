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
    ``errors`` is non-empty the caller should reject with 400.

    The intake form gates the instant quote, so every field is required:
    first name, last name, property address, phone, AND email.

    A combined ``name`` is also accepted (and split) for backward compatibility.
    """
    errors: List[str] = []

    first = _clean(payload.get("first_name"))
    last = _clean(payload.get("last_name"))
    # Back-compat: a single "name" field -> split into first/last.
    if not first and not last and payload.get("name"):
        parts = _clean(payload.get("name")).split()
        if parts:
            first = parts[0]
            last = " ".join(parts[1:])

    email = _clean(payload.get("email")).lower()
    phone_raw = _clean(payload.get("phone"))
    phone_digits = _PHONE_DIGITS_RE.sub("", phone_raw)
    address = _clean(payload.get("address"), limit=300)
    tier = _clean(payload.get("tier")).lower()

    if not first:
        errors.append("First name is required.")
    if not last:
        errors.append("Last name is required.")
    if not address:
        errors.append("Property address is required.")
    if not phone_digits:
        errors.append("Phone number is required.")
    elif len(phone_digits) < 10:
        errors.append("Phone number looks too short.")
    if not email:
        errors.append("Email address is required.")
    elif not _EMAIL_RE.match(email):
        errors.append("Email address looks invalid.")

    if tier and tier not in _VALID_TIERS:
        # A bad tier isn't fatal — just drop it rather than block the lead.
        tier = ""

    full_name = " ".join(p for p in (first, last) if p)
    lead: Dict[str, Any] = {
        "first_name": first,
        "last_name": last,
        "name": full_name,
        "email": email,
        "phone": phone_digits,
        "address": address,
        "tier": tier or None,
        "estimate_low": payload.get("estimate_low"),
        "estimate_high": payload.get("estimate_high"),
        "source": "roofnow_instant_quote",
    }
    return lead, errors

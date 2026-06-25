"""Lead capture validation."""
import pytest

from roofwall.quote.lead import validate_lead


def test_valid_lead_with_email():
    lead, errors = validate_lead({
        "name": "Jane Roof", "email": "Jane@Example.com",
        "address": "1 Oak St", "tier": "better",
    })
    assert errors == []
    assert lead["email"] == "jane@example.com"
    assert lead["tier"] == "better"
    assert lead["source"] == "roofnow_instant_quote"


def test_valid_lead_with_phone_only():
    lead, errors = validate_lead({
        "name": "Bob", "phone": "(555) 123-4567", "address": "2 Elm St",
    })
    assert errors == []
    assert lead["phone"] == "5551234567"


def test_missing_name_and_contact_errors():
    lead, errors = validate_lead({"address": "3 Pine"})
    assert any("Name" in e for e in errors)
    assert any("email or phone" in e for e in errors)


def test_invalid_email():
    _, errors = validate_lead({
        "name": "X", "email": "not-an-email", "address": "4 Ash",
    })
    assert any("Email" in e for e in errors)


def test_short_phone():
    _, errors = validate_lead({
        "name": "X", "phone": "12345", "address": "5 Birch",
    })
    assert any("Phone" in e for e in errors)


def test_missing_address():
    _, errors = validate_lead({"name": "X", "email": "a@b.co"})
    assert any("address" in e.lower() for e in errors)


def test_bad_tier_dropped_not_fatal():
    lead, errors = validate_lead({
        "name": "X", "email": "a@b.co", "address": "6 Cedar", "tier": "platinum",
    })
    assert errors == []
    assert lead["tier"] is None
